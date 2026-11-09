"""Whole declared-snapshot screening, version 2; no external calls or trading."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import AwareDatetime, model_validator

from investment_os.application.market_data import MarketDto
from investment_os.application.opportunities import (
    FunnelQuery,
    FunnelRow,
    OpportunityError,
    OpportunityService,
    bound_global_candidates,
    query_rule_hash,
)
from investment_os.application.universe_snapshots import (
    UniverseError,
    UniverseRun,
    UniverseSnapshot,
    UniverseSummary,
)


class CompleteScopeCommand(UniverseRun):
    protocol_version: Literal["declared-complete-scan-v2"] = "declared-complete-scan-v2"


class CompleteScopeRun(MarketDto):
    schema_version: Literal["2.0"] = "2.0"
    command: CompleteScopeCommand
    source: UniverseSummary
    effective_as_of: AwareDatetime
    ingested_at: AwareDatetime
    rule_hash: str
    rows: tuple[FunnelRow, ...]
    candidate_ids: tuple[UUID, ...]
    formula_version: Literal["manual-screen-v1"] = "manual-screen-v1"
    ranking_version: Literal["global-price-change-v2"] = "global-price-change-v2"
    deep_research: Literal["NOT_PROVIDED"] = "NOT_PROVIDED"
    market_universe: Literal["NOT_PROVIDED"] = "NOT_PROVIDED"
    external_calls: Literal[0] = 0
    model_calls: Literal[0] = 0
    paid_calls: Literal[0] = 0
    auto_trade: Literal[False] = False

    @model_validator(mode="after")
    def validate_complete_result(self) -> Self:
        if (
            self.source.content_hash != self.command.snapshot_hash
            or self.effective_as_of > self.ingested_at
            or (self.command.as_of is not None and self.command.as_of != self.effective_as_of)
            or self.source.source.declared_total != self.source.member_count
            or self.effective_as_of
            < max(
                self.source.source.observed_at,
                self.source.source.effective_at,
                self.source.source.available_at,
                self.source.ingested_at,
            )
            or len(self.rows) != self.source.member_count
            or len({row.instrument_id for row in self.rows}) != len(self.rows)
            or len(self.candidate_ids) > self.command.candidate_limit
            or {r.instrument_id for r in self.rows if r.candidate} != set(self.candidate_ids)
        ):
            raise ValueError("complete scope result mismatch")
        predicate = FunnelQuery(
            **self.command.model_dump(exclude={"snapshot_hash", "as_of", "protocol_version"}),
            instrument_ids=(),
            scope_name=self.source.source.source_name,
            scope_locator=f"universe_snapshot:{self.source.snapshot_id}:{self.source.content_hash}",
            as_of=self.effective_as_of,
        )
        if self.rule_hash != query_rule_hash(predicate):
            raise ValueError("rule hash mismatch")
        eligible = []
        for row in self.rows:
            if row.lifecycle_snapshot and row.lifecycle_snapshot.as_of != self.effective_as_of:
                raise ValueError("lifecycle as-of mismatch")
            stages = row.stages
            if tuple(s.stage for s in stages[:4]) != (
                "BASIC",
                "FINANCIAL",
                "GROWTH_VALUATION",
                "TIMING",
            ):
                raise ValueError("invalid stage sequence")
            passed = all(s.status == "PASSED" for s in stages[:4])
            if passed:
                if len(stages) != 5 or stages[4].stage != "BOUND":
                    raise ValueError("qualified row lacks bound")
                if stages[4].status != ("PASSED" if row.candidate else "REJECTED"):
                    raise ValueError("invalid bound status")
                eligible.append(row)
            elif len(stages) != 4 or row.candidate:
                raise ValueError("unqualified row cannot become candidate")
            if row.candidate and (
                len(set(row.evidence_ids)) < 2
                or {s.stage for s in row.stages if s.status == "PASSED"}
                != {"BASIC", "FINANCIAL", "GROWTH_VALUATION", "TIMING", "BOUND"}
            ):
                raise ValueError("candidate lacks proven gates")
        try:
            if any(not Decimal(row.features["price_change"]).is_finite() for row in eligible):
                raise ValueError("invalid ranking input")
            ordered = sorted(
                eligible,
                key=lambda row: (
                    Decimal(row.features["price_change"]).copy_negate(),
                    row.market,
                    row.symbol,
                    str(row.instrument_id),
                ),
            )
            if (
                tuple(r.instrument_id for r in ordered[: self.command.candidate_limit])
                != self.candidate_ids
            ):
                raise ValueError("candidate order mismatch")
        except (KeyError, ArithmeticError):
            raise ValueError("invalid ranking input") from None
        return self


def validate_complete_snapshot(snapshot: UniverseSnapshot, run: CompleteScopeRun) -> None:
    expected = {
        member.instrument_id: (member.market, member.symbol, member.name)
        for member in snapshot.members
    }
    actual = {row.instrument_id: (row.market, row.symbol, row.name) for row in run.rows}
    if (
        run.source != UniverseSummary.model_validate(snapshot.model_dump(exclude={"members"}))
        or len(expected) != len(snapshot.members)
        or actual != expected
    ):
        raise UniverseError("UNIVERSE_IDENTITY_MISMATCH")


class CompleteScopeSummary(MarketDto):
    run_id: UUID
    snapshot_id: UUID
    source_name: str
    source_version: str
    member_count: int
    candidate_count: int
    as_of: AwareDatetime
    ingested_at: AwareDatetime


class CompleteScopeStore(Protocol):
    async def get(self, snapshot_id: UUID) -> UniverseSnapshot: ...
    async def get_complete(self, run_id: UUID) -> CompleteScopeRun | None: ...
    async def list_complete(self) -> tuple[CompleteScopeRun, ...]: ...
    async def replay_complete(
        self, snapshot_id: UUID, command: CompleteScopeCommand
    ) -> CompleteScopeRun | None: ...
    async def save_complete(
        self, snapshot: UniverseSnapshot, command: CompleteScopeCommand, run: CompleteScopeRun
    ) -> CompleteScopeRun: ...


class CompleteScopeService:
    def __init__(
        self,
        store: CompleteScopeStore,
        funnel: OpportunityService,
        *,
        now: Callable[[], datetime] | None = None,
    ):
        self.store, self.funnel = store, funnel
        self.now = now or (lambda: datetime.now(UTC))

    async def get(self, run_id: UUID) -> CompleteScopeRun | None:
        return await self.store.get_complete(run_id)

    async def list(self) -> tuple[CompleteScopeSummary, ...]:
        runs = await self.store.list_complete()
        return tuple(
            CompleteScopeSummary(
                run_id=run.command.request_id,
                snapshot_id=run.source.snapshot_id,
                source_name=run.source.source.source_name,
                source_version=run.source.source.source_version,
                member_count=len(run.rows),
                candidate_count=len(run.candidate_ids),
                as_of=run.effective_as_of,
                ingested_at=run.ingested_at,
            )
            for run in runs
        )

    async def run(self, snapshot_id: UUID, command: CompleteScopeCommand) -> CompleteScopeRun:
        replay = await self.store.replay_complete(snapshot_id, command)
        if replay is not None:
            return replay
        snapshot, result = await self.prepare_run(snapshot_id, command)
        return await self.store.save_complete(snapshot, command, result)

    async def prepare_run(
        self, snapshot_id: UUID, command: CompleteScopeCommand
    ) -> tuple[UniverseSnapshot, CompleteScopeRun]:
        """Prepare without writing; a scheduled caller commits with its TaskRun UOW."""
        snapshot = await self.store.get(snapshot_id)
        if snapshot.content_hash != command.snapshot_hash:
            raise UniverseError("UNIVERSE_SNAPSHOT_CONFLICT")
        as_of = command.as_of or self.now()
        if as_of > self.now():
            raise OpportunityError("FUTURE_AS_OF_NOT_ALLOWED")
        if as_of < max(
            snapshot.source.observed_at,
            snapshot.source.effective_at,
            snapshot.source.available_at,
            snapshot.ingested_at,
        ):
            raise UniverseError("UNIVERSE_NOT_YET_AVAILABLE")
        ids = tuple(member.instrument_id for member in snapshot.members)
        if (
            not 1 <= len(ids) <= 1000
            or len(ids) != snapshot.member_count
            or len(set(ids)) != len(ids)
        ):
            raise UniverseError("UNIVERSE_IDENTITY_MISMATCH")
        # The legacy query is only a typed predicate carrier; the complete immutable
        # members are resolved and evaluated together, never paginated into runs.
        query = FunnelQuery(
            **command.model_dump(exclude={"snapshot_hash", "as_of", "protocol_version"}),
            instrument_ids=(),
            scope_name=snapshot.source.source_name,
            scope_locator=f"universe_snapshot:{snapshot.snapshot_id}:{snapshot.content_hash}",
            as_of=as_of,
        )
        entries = await self.funnel.resolve_entries(ids)
        expected = {
            member.instrument_id: (
                member.market,
                member.symbol,
                member.name,
                member.currency,
                member.asset_type,
            )
            for member in snapshot.members
        }
        if (
            len(entries) != len(ids)
            or {
                entry.instrument_id: (
                    entry.market,
                    entry.symbol,
                    entry.name,
                    entry.currency,
                    entry.asset_type,
                )
                for entry in entries
            }
            != expected
        ):
            raise UniverseError("UNIVERSE_IDENTITY_MISMATCH")
        rows = await self.funnel.evaluate_entries(query, entries)
        bounded, candidates = bound_global_candidates(rows, command.candidate_limit)
        result = CompleteScopeRun(
            command=command,
            source=UniverseSummary.model_validate(snapshot.model_dump(exclude={"members"})),
            effective_as_of=as_of,
            ingested_at=self.now(),
            rule_hash=query_rule_hash(query),
            rows=bounded,
            candidate_ids=candidates,
        )
        validate_complete_snapshot(snapshot, result)
        return snapshot, result
