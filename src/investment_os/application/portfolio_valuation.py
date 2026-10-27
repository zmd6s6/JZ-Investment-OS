"""Frozen reference valuation context; incomplete inputs never become a SizingRequest."""

import hashlib
import json
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator

from investment_os.application.market_data import (
    MarketDataPort,
    MarketDataRequest,
    MarketDataSnapshot,
    MarketDto,
)
from investment_os.domain.valuation import (
    FORMULA_VERSION,
    HoldingInput,
    nonnegative,
    value_portfolio,
)


class FrozenHolding(MarketDto):
    position_id: UUID
    instrument_id: UUID
    version: int = Field(ge=1)
    market: str
    symbol: str
    name: str
    currency: str
    sector: str
    lot_size: Decimal
    core_quantity: Decimal
    tactical_quantity: Decimal
    core_average_cost: Decimal
    tactical_average_cost: Decimal

    @field_validator(
        "lot_size",
        "core_quantity",
        "tactical_quantity",
        "core_average_cost",
        "tactical_average_cost",
        mode="before",
    )
    @classmethod
    def exact(cls, value: Decimal | str | int) -> Decimal:
        return nonnegative(value)


class FrozenPolicy(MarketDto):
    policy_id: UUID | None = None
    version_id: UUID | None = None
    version: int | None = None
    name: str | None = None
    content_hash: str | None = None
    config_json: str | None = None
    status: str
    reason_code: str


class FrozenPortfolio(MarketDto):
    portfolio_id: UUID
    name: str
    base_currency: str
    cash: Decimal
    captured_at: AwareDatetime
    holdings: tuple[FrozenHolding, ...]
    policy: FrozenPolicy

    @field_validator("cash", mode="before")
    @classmethod
    def exact(cls, value: Decimal | str | int) -> Decimal:
        return nonnegative(value)


class ValuationInputPort(Protocol):
    async def capture(self, portfolio_id: UUID) -> FrozenPortfolio: ...


class HoldingNumbers(MarketDto):
    instrument_id: UUID
    core_value: Decimal | None
    tactical_value: Decimal | None
    total_value: Decimal | None
    core_weight: Decimal | None
    tactical_weight: Decimal | None
    total_weight: Decimal | None


class ValuationContext(MarketDto):
    schema_version: Literal["1.0"] = "1.0"
    formula_version: str = FORMULA_VERSION
    input_hash: str
    output_hash: str
    input_snapshot: FrozenPortfolio
    source: str
    source_name: str
    quotes: tuple[MarketDataSnapshot, ...]
    valuation_status: str
    nav: Decimal | None
    market_value: Decimal | None
    cash_weight: Decimal | None
    gross_exposure: Decimal | None
    net_exposure: Decimal | None
    sector_weights: dict[str, Decimal]
    holdings: tuple[HoldingNumbers, ...]
    sizing_ready: Literal[False] = False
    trading_grade: Literal[False] = False
    auto_trade: Literal[False] = False
    instrument_volatility: None = None
    liquidity_capacity: None = None
    risk_budget_capacity: None = None
    pending_capacity: None = None
    blockers: tuple[str, ...]


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def validate_quote(request: MarketDataRequest, snapshot: MarketDataSnapshot) -> None:
    if any(
        getattr(snapshot, key) != getattr(request, key)
        for key in ("instrument_id", "source", "source_name", "as_of", "base_currency")
    ):
        raise ValueError("VALUATION_QUOTE_RESPONSE_MISMATCH")
    provenance = snapshot.provenance
    if snapshot.status == "AVAILABLE" and (
        not provenance
        or not snapshot.quote
        or (
            provenance.instrument_id != request.instrument_id
            or provenance.currency != request.base_currency
            or provenance.source != request.source
            or provenance.source_name != request.source_name
            or max(
                provenance.observed_at,
                provenance.effective_at,
                provenance.available_at,
                provenance.ingested_at,
            )
            > request.as_of
            or provenance.expires_at <= request.as_of
        )
    ):
        raise ValueError("VALUATION_QUOTE_INVALID")


class PortfolioValuationService:
    def __init__(self, inputs: ValuationInputPort, market: MarketDataPort):
        self._inputs = inputs
        self._market = market

    async def get_context(
        self, portfolio_id: UUID, *, source: str, source_name: str
    ) -> ValuationContext:
        if not source.strip() or not source_name.strip():
            raise ValueError("EXPLICIT_SOURCE_REQUIRED")
        book = await self._inputs.capture(portfolio_id)
        if book.portfolio_id != portfolio_id:
            raise ValueError("VALUATION_PORTFOLIO_RESPONSE_MISMATCH")
        book = book.model_copy(
            update={"holdings": tuple(sorted(book.holdings, key=lambda h: str(h.instrument_id)))}
        )
        quotes: list[MarketDataSnapshot] = []
        prices: dict[UUID, Decimal] = {}
        blockers = [
            "HISTORICAL_VOLATILITY_UNAVAILABLE",
            "LIQUIDITY_UNAVAILABLE",
            "RISK_BUDGET_UNAVAILABLE",
            "CORRELATION_UNAVAILABLE",
            "PENDING_CAPACITY_UNAVAILABLE",
            "RISK_AND_THESIS_UNAVAILABLE",
            "SIZING_FORMULA_INPUTS_UNAVAILABLE",
        ]
        if book.policy.reason_code != "POLICY_REFERENCE_VALID":
            blockers.append(book.policy.reason_code)
        fx = book.base_currency != "CNY" or any(
            h.currency != "CNY" and (h.core_quantity > 0 or h.tactical_quantity > 0)
            for h in book.holdings
        )
        if fx:
            blockers.append("FX_REQUIRED")
        for h in sorted(book.holdings, key=lambda h: str(h.instrument_id)):
            if not h.sector.strip() and (h.core_quantity > 0 or h.tactical_quantity > 0):
                blockers.append("SECTOR_UNCLASSIFIED")
            if h.lot_size <= 0:
                blockers.append("LOT_SIZE_INVALID")
            if fx or (h.core_quantity == 0 and h.tactical_quantity == 0):
                continue
            req = MarketDataRequest(
                instrument_id=h.instrument_id,
                source=source,
                source_name=source_name,
                as_of=book.captured_at,
                base_currency=book.base_currency,
            )
            quote = await self._market.get_snapshot(req)
            validate_quote(req, quote)
            quotes.append(quote)
            if quote.quote:
                prices[h.instrument_id] = quote.quote.price
                blockers.append("MANUAL_REFERENCE_NOT_TRADING_GRADE")
            else:
                blockers.append(f"QUOTE_{quote.status}")
        numbers = value_portfolio(
            book.base_currency,
            book.cash,
            tuple(
                HoldingInput(
                    h.instrument_id,
                    h.currency,
                    h.sector,
                    h.core_quantity,
                    h.tactical_quantity,
                    prices.get(h.instrument_id),
                )
                for h in book.holdings
            ),
        )
        if numbers.nav is None or numbers.nav <= 0:
            blockers.append("NAV_UNAVAILABLE" if numbers.nav is None else "ZERO_NAV")
        payload = {
            "formula_version": FORMULA_VERSION,
            "input_snapshot": book.model_dump(mode="json"),
            "source": source,
            "source_name": source_name,
            "quotes": [q.model_dump(mode="json") for q in quotes],
        }
        input_hash = fingerprint(payload)
        context = ValuationContext(
            input_hash=input_hash,
            output_hash="",
            input_snapshot=book,
            source=source,
            source_name=source_name,
            quotes=tuple(quotes),
            valuation_status=numbers.status,
            nav=numbers.nav,
            market_value=numbers.market_value,
            cash_weight=numbers.cash_weight,
            gross_exposure=numbers.gross_exposure,
            net_exposure=numbers.net_exposure,
            sector_weights=dict(numbers.sector_weights),
            holdings=tuple(
                HoldingNumbers(**{name: getattr(row, name) for name in HoldingNumbers.model_fields})
                for row in numbers.holdings
            ),
            blockers=tuple(sorted(set(blockers))),
        )
        return context.model_copy(
            update={
                "output_hash": fingerprint(context.model_dump(mode="json", exclude={"output_hash"}))
            }
        )
