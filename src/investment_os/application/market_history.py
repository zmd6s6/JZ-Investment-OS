"""有界历史日线的描述性统计; 不替代交易级风险输入。"""

from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from investment_os.application.analysis_models import digest
from investment_os.application.market_features import DailyMarketBar, MarketDecimal
from investment_os.domain.values import UtcTimestamp


class MarketHistory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    instrument_id: UUID
    reference_at: datetime
    status: Literal["RECEIVED", "UNAVAILABLE"]
    reason: Literal["REQUEST_FAILED", "INVALID_RESPONSE", "NO_DATA", "NOT_PROVIDED"] | None = None
    bars: tuple[DailyMarketBar, ...] = Field(default=(), max_length=90)

    @model_validator(mode="after")
    def valid_history(self) -> Self:
        reference = UtcTimestamp(self.reference_at).value
        if (self.status == "UNAVAILABLE") != (self.reason is not None):
            raise ValueError("history status and reason disagree")
        if self.status == "UNAVAILABLE" and self.bars:
            raise ValueError("unavailable history cannot carry accepted bars")
        dates = []
        for value in self.bars:
            bar = DailyMarketBar.model_validate(
                {name: getattr(value, name) for name in DailyMarketBar.model_fields}
            )
            if (
                bar.instrument_id != self.instrument_id
                or bar.as_of > reference
                or bar.as_of < reference - timedelta(days=89)
            ):
                raise ValueError("history identity or window invalid")
            dates.append(bar.as_of.date())
        if dates != sorted(dates) or len(set(dates)) != len(dates):
            raise ValueError("history must be ordered with unique dates")
        if self.status == "RECEIVED" and (not self.bars or self.bars[-1].as_of != reference):
            raise ValueError("history must end at the reference quote")
        return self


class HistoricalMarketFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0"] = "1.0"
    calculation_version: Literal["observed-daily-20-v1"] = "observed-daily-20-v1"
    input_hash: str
    history: MarketHistory
    source: str
    currency: str
    source_rank: int
    degraded: bool
    sample_count: int
    required_count: Literal[20] = 20
    daily_return_sample_stddev: MarketDecimal | None
    compounded_daily_return: MarketDecimal | None
    mean_volume_shares: MarketDecimal | None
    mean_turnover: MarketDecimal | None
    missing_fields: tuple[str, ...]
    availability: Literal["PROVIDER_TIME_ONLY"] = "PROVIDER_TIME_ONLY"
    sizing_ready: Literal[False] = False


def build_historical_features(
    history: MarketHistory, *, source: str, currency: str, source_rank: int, degraded: bool
) -> HistoricalMarketFeatures:
    history = MarketHistory.model_validate(
        {name: getattr(history, name) for name in MarketHistory.model_fields}
    )
    if not source.strip() or not currency.strip() or source_rank < 0:
        raise ValueError("historical provenance invalid")
    sample = history.bars[-20:]
    missing = []
    deviation = compounded = volume = turnover = None
    with localcontext(Context(prec=128, rounding=ROUND_HALF_EVEN)):
        if len(sample) != 20:
            missing.append("INSUFFICIENT_20_OBSERVATIONS")
        else:
            if any(b.previous_close is None for b in sample):
                missing.append("PREVIOUS_CLOSE_MISSING")
            else:
                returns = [
                    (b.close - b.previous_close) / b.previous_close
                    for b in sample
                    if b.previous_close is not None
                ]
                mean = sum(returns, Decimal(0)) / Decimal(20)
                deviation = (
                    sum(((r - mean) ** 2 for r in returns), Decimal(0)) / Decimal(19)
                ).sqrt()
                growth = Decimal(1)
                for value in returns:
                    growth *= Decimal(1) + value
                compounded = growth - Decimal(1)
            if any(b.volume_shares is None for b in sample):
                missing.append("VOLUME_MISSING")
            else:
                volume = sum(
                    (b.volume_shares for b in sample if b.volume_shares is not None), Decimal(0)
                ) / Decimal(20)
            if any(b.turnover is None for b in sample):
                missing.append("TURNOVER_MISSING")
            else:
                turnover = sum(
                    (b.turnover for b in sample if b.turnover is not None), Decimal(0)
                ) / Decimal(20)
    return HistoricalMarketFeatures(
        input_hash=digest(
            {
                "version": "observed-daily-20-v1",
                "history": history.model_dump(mode="json"),
                "source": source,
                "currency": currency,
                "source_rank": source_rank,
                "degraded": degraded,
            }
        ),
        history=history,
        source=source,
        currency=currency,
        source_rank=source_rank,
        degraded=degraded,
        sample_count=len(sample),
        daily_return_sample_stddev=deviation,
        compounded_daily_return=compounded,
        mean_volume_shares=volume,
        mean_turnover=turnover,
        missing_fields=tuple(missing),
    )
