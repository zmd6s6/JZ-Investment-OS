"""只读估值对账: 已知值精确计算, 未知输入不冒充零或满额容量。"""

from dataclasses import replace
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from investment_os.application.analysis_models import digest
from investment_os.application.market_data import MarketQuote, ensure_daily_bar, ensure_price
from investment_os.application.market_features import DailyMarketFeatures, build_daily_features
from investment_os.application.market_history import (
    HistoricalMarketFeatures,
    build_historical_features,
)
from investment_os.application.portfolio_book import PortfolioView
from investment_os.domain.errors import DomainError
from investment_os.domain.values import UtcTimestamp, exact_decimal

ExactDecimal = Annotated[
    Decimal, PlainSerializer(lambda value: format(value, "f"), return_type=str, when_used="json")
]


class ValuationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PositionValuation(ValuationModel):
    instrument_id: UUID
    symbol: str
    name: str
    currency: str
    sector: str | None
    core_quantity: ExactDecimal
    tactical_quantity: ExactDecimal
    quantity: ExactDecimal
    price: ExactDecimal | None = None
    source: str | None = None
    source_rank: int | None = None
    degraded: bool | None = None
    quote_as_of: datetime | None = None
    core_value: ExactDecimal | None = None
    tactical_value: ExactDecimal | None = None
    market_value: ExactDecimal | None = None
    core_weight: ExactDecimal | None = None
    tactical_weight: ExactDecimal | None = None
    weight: ExactDecimal | None = None


class SectorValuation(ValuationModel):
    sector: str
    market_value: ExactDecimal
    weight: ExactDecimal | None
    classification_source: Literal["PORTFOLIO_INPUT"] = "PORTFOLIO_INPUT"


class AnalysisValuation(ValuationModel):
    schema_version: Literal["1.0"] = "1.0"
    calculation_version: Literal["portfolio-valuation-v1"] = "portfolio-valuation-v1"
    status: Literal["OK", "PARTIAL", "FAILED"]
    as_of: datetime
    input_hash: str
    instrument_id: UUID
    portfolio_id: UUID
    base_currency: str
    cash_balance: ExactDecimal
    nav: ExactDecimal | None
    holdings_value: ExactDecimal | None
    gross_exposure: ExactDecimal | None
    cash_weight: ExactDecimal | None
    target_reference_price: ExactDecimal | None
    target_currency: str
    target_quote_as_of: datetime | None
    target_core_weight: ExactDecimal | None
    target_tactical_weight: ExactDecimal | None
    target_weight: ExactDecimal | None
    source: str | None
    source_rank: int | None
    degraded: bool | None
    missing_quotes: tuple[UUID, ...]
    currencies: tuple[str, ...]
    quote_sources: tuple[str, ...]
    degraded_instruments: tuple[UUID, ...]
    position_values: tuple[PositionValuation, ...]
    sector_values: tuple[SectorValuation, ...]
    unclassified_value: ExactDecimal | None
    reason_codes: tuple[str, ...]
    single_currency_limit: Literal[True] = True
    price_availability: Literal["PROVIDER_TIME_ONLY"] = "PROVIDER_TIME_ONLY"
    target_market_features: DailyMarketFeatures | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    target_historical_features: HistoricalMarketFeatures | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


def build_analysis_valuation(
    *,
    portfolio: PortfolioView,
    target_id: UUID,
    target_currency: str,
    as_of: datetime,
    quotes: dict[UUID, MarketQuote],
) -> AnalysisValuation:
    """仅使用冻结持仓与本次返回价格; 不读当前组合、不补价、不推定 FX。

    128 位计算上下文隔离调用者 Decimal 精度; Core + Tactical 值精确相加,
    总权重从两桶权重相加, 保留实际值, 不截成合规外观。
    """
    as_of = UtcTimestamp(as_of).value
    cash = exact_decimal(portfolio.cash_balance)
    positions = sorted(portfolio.positions, key=lambda p: str(p.instrument_id))
    identities = {p.instrument_id for p in positions} | {target_id}
    reasons: list[str] = []
    valid: dict[UUID, MarketQuote] = {}
    expected = {p.instrument_id: p.currency for p in positions}
    expected.setdefault(target_id, target_currency)
    if len({p.instrument_id for p in positions}) != len(positions) or cash < 0:
        reasons.append("VALUATION_INPUT_INVALID")
    for identity, quote in quotes.items():
        try:
            if (
                identity not in identities
                or quote.instrument_id != identity
                or UtcTimestamp(quote.as_of).value > as_of
                or quote.currency != expected[identity]
                or not quote.source.strip()
                or quote.source_rank < 0
            ):
                raise ValueError("invalid reference quote")
            ensure_daily_bar(quote)
            valid[identity] = replace(
                quote,
                reference_price=ensure_price(quote.reference_price),
                as_of=UtcTimestamp(quote.as_of).value,
            )
        except (ValueError, TypeError, DomainError):
            reasons.append("INVALID_REFERENCE_QUOTES")
    currencies = tuple(sorted({portfolio.base_currency, target_currency, *expected.values()}))
    fx_missing = len(currencies) != 1
    if fx_missing:
        reasons.append("FX_SOURCE_MISSING_MULTI_CURRENCY")
    # A zero holding needs no quote, unless it is also the analysis target.
    required = {target_id} | {
        p.instrument_id for p in positions if p.core_quantity != 0 or p.tactical_quantity != 0
    }
    missing = tuple(sorted(required - valid.keys(), key=str))
    if missing:
        reasons.append("MISSING_REFERENCE_QUOTES")
    with localcontext(Context(prec=128, rounding=ROUND_HALF_EVEN)):
        rows: list[PositionValuation] = []
        for p in positions:
            core, tactical = exact_decimal(p.core_quantity), exact_decimal(p.tactical_quantity)
            if core < 0 or tactical < 0:
                reasons.append("VALUATION_INPUT_INVALID")
            q = valid.get(p.instrument_id)
            core_value = core * q.reference_price if q else Decimal("0") if core == 0 else None
            tactical_value = (
                tactical * q.reference_price if q else Decimal("0") if tactical == 0 else None
            )
            rows.append(
                PositionValuation(
                    instrument_id=p.instrument_id,
                    symbol=p.symbol,
                    name=p.name,
                    currency=p.currency,
                    sector=p.sector.strip() or None,
                    core_quantity=core,
                    tactical_quantity=tactical,
                    quantity=core + tactical,
                    price=q.reference_price if q else None,
                    source=q.source if q else None,
                    source_rank=q.source_rank if q else None,
                    degraded=q.degraded if q else None,
                    quote_as_of=q.as_of if q else None,
                    core_value=core_value,
                    tactical_value=tactical_value,
                    market_value=core_value + tactical_value
                    if core_value is not None and tactical_value is not None
                    else None,
                )
            )
        invalid = any(r in reasons for r in ("VALUATION_INPUT_INVALID", "INVALID_REFERENCE_QUOTES"))
        complete = not fx_missing and not invalid and all(r.market_value is not None for r in rows)
        holdings = (
            sum((r.market_value or Decimal("0") for r in rows), Decimal("0")) if complete else None
        )
        nav = cash + holdings if holdings is not None else None
        if nav is not None and nav <= 0:
            reasons.append("NAV_NON_POSITIVE")
        weights_known = nav is not None and nav > 0
        if weights_known:
            assert nav is not None
            rows = [
                r.model_copy(
                    update={
                        "core_weight": (r.core_value or Decimal("0")) / nav,
                        "tactical_weight": (r.tactical_value or Decimal("0")) / nav,
                        "weight": (r.core_value or Decimal("0")) / nav
                        + (r.tactical_value or Decimal("0")) / nav,
                    }
                )
                for r in rows
            ]
        target = valid.get(target_id)
        daily_features = None
        if target is not None and target.daily_bar is not None:
            daily_features = build_daily_features(
                target.daily_bar,
                currency=target.currency,
                source=target.source,
                source_rank=target.source_rank,
                degraded=target.degraded,
            )
        target_position = next((r for r in rows if r.instrument_id == target_id), None)
        historical_features = (
            build_historical_features(
                target.history,
                source=target.source,
                currency=target.currency,
                source_rank=target.source_rank,
                degraded=target.degraded,
            )
            if target is not None and target.history is not None
            else None
        )
        sectors: dict[str, Decimal] = {}
        unclassified = Decimal("0") if complete else None
        if complete:
            for row in rows:
                if row.sector is None:
                    assert unclassified is not None
                    unclassified += row.market_value or Decimal("0")
                else:
                    sectors[row.sector] = sectors.get(row.sector, Decimal("0")) + (
                        row.market_value or Decimal("0")
                    )
        snapshot = {
            "version": "portfolio-valuation-v1",
            "portfolio_id": str(portfolio.portfolio_id),
            "base_currency": portfolio.base_currency,
            "cash_balance": str(cash),
            "target_id": str(target_id),
            "target_currency": target_currency,
            "as_of": as_of.isoformat(),
            "positions": [r.model_dump(mode="json") for r in rows],
            "target_quote": {
                "price": str(target.reference_price),
                "currency": target.currency,
                "as_of": target.as_of.isoformat(),
                "source": target.source,
                "rank": target.source_rank,
                "degraded": target.degraded,
            }
            if target
            else None,
            "reason_codes": sorted(set(reasons)),
        }
        zero = Decimal("0") if weights_known else None
        if daily_features is not None:
            snapshot["target_market_features"] = daily_features.model_dump(mode="json")
        if historical_features is not None:
            snapshot["target_historical_features"] = historical_features.model_dump(mode="json")
        return AnalysisValuation(
            status="FAILED"
            if invalid or fx_missing or "NAV_NON_POSITIVE" in reasons
            else "PARTIAL"
            if missing
            else "OK",
            as_of=as_of,
            input_hash=digest(snapshot),
            instrument_id=target_id,
            portfolio_id=portfolio.portfolio_id,
            base_currency=portfolio.base_currency,
            cash_balance=cash,
            nav=nav,
            holdings_value=holdings,
            gross_exposure=holdings / nav
            if weights_known and holdings is not None and nav
            else None,
            cash_weight=cash / nav if weights_known and nav else None,
            target_reference_price=target.reference_price if target else None,
            target_currency=target_currency,
            target_quote_as_of=target.as_of if target else None,
            target_core_weight=target_position.core_weight if target_position else zero,
            target_tactical_weight=target_position.tactical_weight if target_position else zero,
            target_weight=target_position.weight if target_position else zero,
            source=target.source if target else None,
            source_rank=target.source_rank if target else None,
            degraded=target.degraded if target else None,
            missing_quotes=missing,
            currencies=currencies,
            quote_sources=tuple(sorted({q.source for q in valid.values()})),
            degraded_instruments=tuple(
                sorted((i for i, q in valid.items() if q.degraded), key=str)
            ),
            position_values=tuple(rows),
            sector_values=tuple(
                SectorValuation(
                    sector=s, market_value=v, weight=v / nav if weights_known and nav else None
                )
                for s, v in sorted(sectors.items())
            ),
            unclassified_value=unclassified,
            reason_codes=tuple(dict.fromkeys(reasons)),
            target_market_features=daily_features,
            target_historical_features=historical_features,
        )
