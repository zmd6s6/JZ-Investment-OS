"""单日描述性行情观察; 不将振幅或成交额冒充波动率或交易容量。"""

from datetime import datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    PlainSerializer,
    field_validator,
    model_validator,
)

from investment_os.application.analysis_models import digest
from investment_os.domain.values import UtcTimestamp, exact_decimal

MarketDecimal = Annotated[
    Decimal,
    BeforeValidator(exact_decimal),
    PlainSerializer(lambda value: format(value, "f"), return_type=str, when_used="json"),
]


class DailyMarketBar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    instrument_id: UUID
    as_of: datetime
    close: MarketDecimal
    open: MarketDecimal | None = None
    high: MarketDecimal | None = None
    low: MarketDecimal | None = None
    previous_close: MarketDecimal | None = None
    volume_shares: MarketDecimal | None = None
    turnover: MarketDecimal | None = None
    previous_close_basis: Literal["PROVIDER_REPORTED", "EX_RIGHTS"] = "PROVIDER_REPORTED"

    @field_validator("as_of")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return UtcTimestamp(value).value

    @model_validator(mode="after")
    def valid_bar(self) -> Self:
        prices = [p for p in (self.open, self.high, self.low, self.close) if p is not None]
        if any(p <= 0 for p in prices) or (
            self.previous_close is not None and self.previous_close <= 0
        ):
            raise ValueError("daily prices must be positive")
        if any(v is not None and v < 0 for v in (self.volume_shares, self.turnover)):
            raise ValueError("daily volume and turnover cannot be negative")
        if (self.high is not None and self.high < max(prices)) or (
            self.low is not None and self.low > min(prices)
        ):
            raise ValueError("daily OHLC range is inconsistent")
        return self


class DailyMarketFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0"] = "1.0"
    calculation_version: Literal["daily-observations-v1"] = "daily-observations-v1"
    status: Literal["OK", "PARTIAL"]
    input_hash: str
    bar: DailyMarketBar
    currency: str
    source: str
    source_rank: int
    degraded: bool
    daily_return: MarketDecimal | None
    intraday_range: MarketDecimal | None
    volume_shares: MarketDecimal | None
    turnover: MarketDecimal | None
    missing_fields: tuple[str, ...]
    availability: Literal["PROVIDER_TIME_ONLY"] = "PROVIDER_TIME_ONLY"
    sizing_ready: Literal[False] = False


def build_daily_features(
    bar: DailyMarketBar, *, currency: str, source: str, source_rank: int, degraded: bool
) -> DailyMarketFeatures:
    # Revalidate even model_copy(update=...) values; never trust derived output.
    bar = DailyMarketBar.model_validate(
        {name: getattr(bar, name) for name in DailyMarketBar.model_fields}
    )
    if not currency.strip() or not source.strip() or source_rank < 0:
        raise ValueError("daily quote provenance invalid")
    missing = tuple(
        name
        for name in ("open", "high", "low", "previous_close", "volume_shares", "turnover")
        if getattr(bar, name) is None
    )
    with localcontext(Context(prec=128, rounding=ROUND_HALF_EVEN)):
        daily_return = (
            (bar.close - bar.previous_close) / bar.previous_close
            if bar.previous_close is not None
            else None
        )
        intraday_range = (
            (bar.high - bar.low) / bar.previous_close
            if bar.high is not None and bar.low is not None and bar.previous_close is not None
            else None
        )
    return DailyMarketFeatures(
        status="PARTIAL" if missing else "OK",
        input_hash=digest(
            {
                "version": "daily-observations-v1",
                "bar": bar.model_dump(mode="json"),
                "currency": currency,
                "source": source,
                "source_rank": source_rank,
                "degraded": degraded,
            }
        ),
        bar=bar,
        currency=currency,
        source=source,
        source_rank=source_rank,
        degraded=degraded,
        daily_return=daily_return,
        intraday_range=intraday_range,
        volume_shares=bar.volume_shares,
        turnover=bar.turnover,
        missing_fields=missing,
    )
