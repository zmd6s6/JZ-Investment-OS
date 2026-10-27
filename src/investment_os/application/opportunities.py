"""Bounded research queries over explicit manual scope, never investment actions."""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Annotated, Literal, Protocol, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, field_validator, model_validator

from investment_os.application.instrument_catalog import InstrumentCatalogEntry
from investment_os.application.market_data import (
    MarketDataRequest,
    MarketDataSnapshot,
    MarketDto,
    Text,
)

Exact = Annotated[
    str, StringConstraints(strict=True, pattern=r"^-?(0|[1-9][0-9]{0,19})(\.[0-9]{1,18})?$")
]


class OpportunityError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ManualScreenFacts(MarketDto):
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID
    instrument_id: UUID
    source_name: Text
    source_locator: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    observed_at: AwareDatetime
    effective_at: AwareDatetime
    available_at: AwareDatetime
    expires_at: AwareDatetime
    previous_close_at: AwareDatetime | None = None
    revenue_current: Exact | None = None
    revenue_previous: Exact | None = None
    net_income: Exact | None = None
    annual_diluted_shares: Exact | None = None
    fiscal_year: Annotated[int, Field(strict=True, ge=1900, le=2200)] | None = None
    financial_basis: Literal["CALENDAR_YEAR_CONSOLIDATED_CNY"] | None = None
    net_income_basis: Literal["ATTRIBUTABLE_TO_ORDINARY_SHAREHOLDERS"] | None = None
    quote_evidence_id: UUID | None = None
    same_share_basis: bool | None = None
    previous_close: Exact | None = None
    currency: Literal["CNY"] = "CNY"
    suspended: bool | None = None

    @field_validator(
        "observed_at", "effective_at", "available_at", "expires_at", "previous_close_at"
    )
    @classmethod
    def utc(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value else None

    @model_validator(mode="after")
    def valid_times_and_denominators(self) -> Self:
        if (
            self.available_at < max(self.observed_at, self.effective_at)
            or self.expires_at <= self.available_at
        ):
            raise ValueError("invalid business times")
        if self.previous_close_at and self.previous_close_at > self.available_at:
            raise ValueError("previous close must be known at availability")
        if (
            self.fiscal_year
            and datetime(self.fiscal_year, 12, 31, 23, 59, 59, tzinfo=UTC) > self.available_at
        ):
            raise ValueError("annual period cannot end after fact availability")
        for name in (
            "revenue_current",
            "revenue_previous",
            "annual_diluted_shares",
            "previous_close",
        ):
            value = getattr(self, name)
            if value is not None and Decimal(value) <= 0:
                raise ValueError("denominators and reference values must be positive")
        return self


class FactReceipt(MarketDto):
    request_id: UUID
    evidence_id: UUID
    content_hash: str
    ingested_at: AwareDatetime


class FactSnapshot(MarketDto):
    status: Literal["AVAILABLE", "MISSING", "EXPIRED", "NOT_YET_AVAILABLE", "INVALID"]
    facts: ManualScreenFacts | None = None
    evidence_id: UUID | None = None
    content_hash: str | None = None
    ingested_at: AwareDatetime | None = None


class FunnelQuery(MarketDto):
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID
    instrument_ids: Annotated[tuple[UUID, ...], Field(max_length=200)]
    scope_name: Text
    scope_locator: Text
    scope_kind: Literal["LOCAL_EXPLICIT_LIST"] = "LOCAL_EXPLICIT_LIST"
    quote_source_name: Text
    fact_source_name: Text
    as_of: AwareDatetime
    candidate_limit: Annotated[int, Field(strict=True, ge=1, le=20)]
    rule_set_version: Literal["manual-screen-query-v1"] = "manual-screen-query-v1"
    min_profit_margin: Exact
    min_revenue_growth: Exact
    max_pe: Exact
    min_price_change: Exact

    @field_validator("as_of")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bounded_unique(self) -> Self:
        if len(self.instrument_ids) != len(set(self.instrument_ids)):
            raise ValueError("duplicate instruments are not allowed")
        if Decimal(self.max_pe) <= 0:
            raise ValueError("max PE must be positive")
        return self


def query_rule_hash(query: FunnelQuery) -> str:
    fields = (
        "rule_set_version",
        "min_profit_margin",
        "min_revenue_growth",
        "max_pe",
        "min_price_change",
        "candidate_limit",
    )
    return hashlib.sha256(
        json.dumps(
            {name: getattr(query, name) for name in fields}, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


class StageResult(MarketDto):
    stage: Literal["BASIC", "FINANCIAL", "GROWTH_VALUATION", "TIMING", "BOUND"]
    status: Literal["PASSED", "REJECTED", "MISSING", "NOT_REACHED"]
    reason: str
    missing_fields: tuple[str, ...] = ()


class FunnelRow(MarketDto):
    instrument_id: UUID
    market: str
    symbol: str
    name: str
    sector: str
    lifecycle_state: str | None = None
    stages: tuple[StageResult, ...]
    features: dict[str, str]
    evidence_ids: tuple[UUID, ...]
    input_hashes: tuple[str, ...]
    quote: MarketDataSnapshot | None = None
    facts: FactSnapshot | None = None
    candidate: bool = False
    next_condition: str


class FunnelRun(MarketDto):
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID
    query: FunnelQuery
    formula_version: Literal["manual-screen-v1"] = "manual-screen-v1"
    ingested_at: AwareDatetime
    query_rule_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["COMPLETE", "DEGRADED", "EMPTY"]
    rows: tuple[FunnelRow, ...]
    candidate_ids: tuple[UUID, ...]
    deep_research: Literal["NOT_PROVIDED"] = "NOT_PROVIDED"
    market_universe: Literal["NOT_PROVIDED"] = "NOT_PROVIDED"
    independently_verified: Literal[False] = False
    auto_trade: Literal[False] = False

    @model_validator(mode="after")
    def invariant(self) -> Self:
        if self.run_id != self.query.request_id or self.query_rule_hash != query_rule_hash(
            self.query
        ):
            raise ValueError("run identity or rule hash mismatch")
        if (
            len(set(self.candidate_ids)) != len(self.candidate_ids)
            or len(self.candidate_ids) > self.query.candidate_limit
        ):
            raise ValueError("candidate bounds violated")
        if len(self.rows) != len(self.query.instrument_ids) or {
            r.instrument_id for r in self.rows
        } != set(self.query.instrument_ids):
            raise ValueError("run universe mismatch")
        if {r.instrument_id for r in self.rows if r.candidate} != set(self.candidate_ids):
            raise ValueError("candidate membership mismatch")
        return self


class UniversePort(Protocol):
    async def resolve(
        self, instrument_ids: tuple[UUID, ...]
    ) -> tuple[InstrumentCatalogEntry, ...]: ...


class ScreenFactsPort(Protocol):
    async def save_facts(self, command: ManualScreenFacts) -> FactReceipt: ...
    async def get_facts(
        self, instrument_id: UUID, source_name: str, as_of: datetime
    ) -> FactSnapshot: ...


class FunnelMarketPort(Protocol):
    async def get_snapshot(self, request: MarketDataRequest) -> MarketDataSnapshot: ...


class FunnelRunPort(Protocol):
    async def replay(self, query: FunnelQuery) -> FunnelRun | None: ...
    async def save_run(self, run: FunnelRun) -> FunnelRun: ...
    async def get_run(self, run_id: UUID) -> FunnelRun | None: ...
    async def list_runs(self) -> tuple[FunnelRun, ...]: ...


def number(value: str | None) -> Decimal:
    if value is None:
        raise ValueError("missing numeric input")
    return Decimal(value)


def evaluate(
    entry: InstrumentCatalogEntry,
    quote: MarketDataSnapshot,
    snapshot: FactSnapshot,
    query: FunnelQuery,
) -> FunnelRow:
    stages: list[StageResult] = []
    features: dict[str, str] = {}
    ids: list[UUID] = []
    hashes: list[str] = []
    facts = snapshot.facts
    if quote.provenance:
        ids.append(quote.provenance.evidence_id)
        hashes.append(quote.provenance.content_hash)
    if snapshot.evidence_id and snapshot.content_hash:
        ids.append(snapshot.evidence_id)
        hashes.append(snapshot.content_hash)

    def stage(
        name: Literal["BASIC", "FINANCIAL", "GROWTH_VALUATION", "TIMING", "BOUND"],
        *,
        missing: tuple[str, ...] = (),
        passed: bool = True,
        reason: str = "QUERY_CONDITION_MET",
    ) -> None:
        stages.append(
            StageResult(
                stage=name,
                status="MISSING" if missing else "PASSED" if passed else "REJECTED",
                reason="INPUT_NOT_PROVIDED" if missing else reason,
                missing_fields=missing,
            )
        )

    def active() -> bool:
        return all(s.status == "PASSED" for s in stages)

    basic_missing = []
    if quote.status != "AVAILABLE":
        basic_missing.append("quote:" + quote.status)
    if snapshot.status != "AVAILABLE" or facts is None:
        basic_missing.append("facts:" + snapshot.status)
    if facts and facts.suspended is None:
        basic_missing.append("suspended")
    stage(
        "BASIC",
        missing=tuple(basic_missing),
        passed=entry.currency == "CNY" and bool(facts and facts.suspended is False),
        reason="BASIC_REFERENCE_CHECK",
    )
    if active() and facts:
        missing = tuple(
            n
            for n in (
                "revenue_current",
                "net_income",
                "fiscal_year",
                "financial_basis",
                "net_income_basis",
            )
            if getattr(facts, n) is None
        )
        if not missing:
            with localcontext(Context(prec=38, rounding=ROUND_HALF_EVEN)):
                margin = number(facts.net_income) / number(facts.revenue_current)
            features["profit_margin"] = str(margin)
            stage(
                "FINANCIAL",
                passed=margin >= Decimal(query.min_profit_margin),
                reason="PROFIT_MARGIN_QUERY",
            )
        else:
            stage("FINANCIAL", missing=missing)
    if active() and facts and quote.quote:
        missing = tuple(
            n for n in ("revenue_previous", "annual_diluted_shares") if getattr(facts, n) is None
        )
        if facts.same_share_basis is not True:
            missing += ("same_share_basis",)
        if facts.quote_evidence_id != quote.quote.provenance.evidence_id:
            missing += ("quote_evidence_id_matches",)
        if not entry.sector:
            missing += ("sector",)
        if facts.net_income is not None and number(facts.net_income) <= 0:
            missing += ("positive_earnings_for_pe",)
        if not missing:
            with localcontext(Context(prec=38, rounding=ROUND_HALF_EVEN)):
                growth = number(facts.revenue_current) / number(facts.revenue_previous) - 1
                pe = (
                    quote.quote.price
                    * number(facts.annual_diluted_shares)
                    / number(facts.net_income)
                )
            features.update(revenue_growth=str(growth), pe=str(pe))
            stage(
                "GROWTH_VALUATION",
                passed=growth >= Decimal(query.min_revenue_growth) and pe <= Decimal(query.max_pe),
                reason="GROWTH_AND_PE_QUERY",
            )
        else:
            stage("GROWTH_VALUATION", missing=missing)
    if active() and facts and quote.quote:
        missing = tuple(
            n for n in ("previous_close", "previous_close_at") if getattr(facts, n) is None
        )
        if (
            facts.previous_close_at
            and facts.previous_close_at >= quote.quote.provenance.observed_at
        ):
            missing += ("previous_close_before_quote",)
        if not missing:
            with localcontext(Context(prec=38, rounding=ROUND_HALF_EVEN)):
                change = quote.quote.price / number(facts.previous_close) - 1
            features["price_change"] = str(change)
            stage(
                "TIMING",
                passed=change >= Decimal(query.min_price_change),
                reason="PRICE_CHANGE_QUERY",
            )
        else:
            stage("TIMING", missing=missing)
    for name in ("BASIC", "FINANCIAL", "GROWTH_VALUATION", "TIMING"):
        if not any(s.stage == name for s in stages):
            stages.append(
                StageResult(stage=name, status="NOT_REACHED", reason="EARLIER_STAGE_STOPPED")
            )
    passed = active()
    return FunnelRow(
        instrument_id=entry.instrument_id,
        market=entry.market,
        symbol=entry.symbol,
        name=entry.name,
        sector=entry.sector,
        stages=tuple(stages),
        features=features,
        evidence_ids=tuple(ids),
        input_hashes=tuple(hashes),
        quote=quote,
        facts=snapshot,
        candidate=passed,
        next_condition="BOUNDED_RESEARCH_REVIEW_ONLY"
        if passed
        else "REVIEW_MISSING_OR_REJECTED_INPUTS",
    )


class OpportunityService:
    def __init__(
        self,
        universe: UniversePort,
        facts: ScreenFactsPort,
        market: FunnelMarketPort,
        runs: FunnelRunPort,
        *,
        now: Callable[[], datetime] | None = None,
    ):
        self._universe = universe
        self._facts = facts
        self._market = market
        self._runs = runs
        self._now = now or (lambda: datetime.now(UTC))

    async def save_facts(self, command: ManualScreenFacts) -> FactReceipt:
        await self._universe.resolve((command.instrument_id,))
        return await self._facts.save_facts(command)

    async def run(self, query: FunnelQuery) -> FunnelRun:
        replay = await self._runs.replay(query)
        if replay:
            return replay
        if query.as_of > self._now():
            raise OpportunityError("FUTURE_AS_OF_NOT_ALLOWED")
        entries = await self._universe.resolve(query.instrument_ids)
        if {entry.instrument_id for entry in entries} != set(query.instrument_ids):
            raise OpportunityError("UNIVERSE_IDENTITY_MISMATCH")
        rows = []
        for entry in sorted(entries, key=lambda e: (e.market, e.symbol, str(e.instrument_id))):
            quote = await self._market.get_snapshot(
                MarketDataRequest(
                    instrument_id=entry.instrument_id,
                    source="MANUAL_MARKET",
                    source_name=query.quote_source_name,
                    as_of=query.as_of,
                )
            )
            facts = await self._facts.get_facts(
                entry.instrument_id, query.fact_source_name, query.as_of
            )
            if (
                quote.instrument_id,
                quote.source,
                quote.source_name,
                quote.as_of,
                quote.base_currency,
            ) != (
                entry.instrument_id,
                "MANUAL_MARKET",
                query.quote_source_name,
                query.as_of,
                "CNY",
            ):
                raise OpportunityError("MARKET_RESPONSE_MISMATCH")
            if facts.status == "AVAILABLE":
                f = facts.facts
                if (
                    f is None
                    or facts.evidence_id is None
                    or facts.content_hash is None
                    or len(facts.content_hash) != 64
                    or facts.ingested_at is None
                    or f.instrument_id != entry.instrument_id
                    or f.source_name != query.fact_source_name
                    or max(f.observed_at, f.effective_at, f.available_at, facts.ingested_at)
                    > query.as_of
                    or f.expires_at <= query.as_of
                ):
                    facts = FactSnapshot(status="INVALID")
            rows.append(evaluate(entry, quote, facts, query))
        qualified = sorted(
            (row for row in rows if row.candidate),
            key=lambda row: (
                Decimal(row.features["price_change"]).copy_negate(),
                row.market,
                row.symbol,
                str(row.instrument_id),
            ),
        )
        candidates = tuple(row.instrument_id for row in qualified[: query.candidate_limit])
        bounded = []
        for row in rows:
            if row.candidate:
                selected = row.instrument_id in candidates
                row = row.model_copy(
                    update={
                        "candidate": selected,
                        "stages": (
                            *row.stages,
                            StageResult(
                                stage="BOUND",
                                status="PASSED" if selected else "REJECTED",
                                reason="WITHIN_LIMIT" if selected else "CANDIDATE_LIMIT_REACHED",
                            ),
                        ),
                        "next_condition": "DEEP_RESEARCH_NOT_PROVIDED"
                        if selected
                        else "OUTSIDE_CURRENT_RESEARCH_LIMIT",
                    }
                )
            bounded.append(row)
        result = FunnelRun(
            run_id=query.request_id,
            query=query,
            ingested_at=self._now(),
            query_rule_hash=query_rule_hash(query),
            status="EMPTY"
            if not rows
            else "DEGRADED"
            if any(s.status == "MISSING" for row in rows for s in row.stages)
            else "COMPLETE",
            rows=tuple(bounded),
            candidate_ids=candidates,
        )
        return await self._runs.save_run(result)

    async def get_run(self, run_id: UUID) -> FunnelRun | None:
        return await self._runs.get_run(run_id)

    async def list_runs(self) -> tuple[FunnelRun, ...]:
        return await self._runs.list_runs()
