"""Typed, explicit market inputs. A recorded manual quote is not verified trading data."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Annotated, Literal, Protocol, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from investment_os.application.instrument_catalog import (
    InstrumentCatalogEntry,
    InstrumentCatalogService,
)
from investment_os.application.portfolio_book import PortfolioBookService
from investment_os.domain.values import exact_decimal

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
QuoteStatus = Literal[
    "AVAILABLE",
    "MISSING",
    "EXPIRED",
    "NOT_YET_AVAILABLE",
    "INVALID",
    "FX_REQUIRED",
    "UNSUPPORTED_SOURCE",
]


class MarketDataError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class MarketDto(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ManualQuoteInput(MarketDto):
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID
    instrument_id: UUID
    source: Literal["MANUAL_MARKET"] = "MANUAL_MARKET"
    source_name: Text
    source_locator: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
    price: Annotated[
        str, StringConstraints(strict=True, pattern=r"^(0|[1-9][0-9]{0,19})(\.[0-9]{1,18})?$")
    ]
    observed_at: AwareDatetime
    effective_at: AwareDatetime
    available_at: AwareDatetime
    expires_at: AwareDatetime

    @field_validator("observed_at", "effective_at", "available_at", "expires_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @field_validator("price")
    @classmethod
    def positive_exact(cls, value: str) -> str:
        number = exact_decimal(value)
        if number <= 0:
            raise ValueError("quote price must be positive")
        return format(number, "f")

    @model_validator(mode="after")
    def ordered_times(self) -> Self:
        if (
            self.available_at < max(self.observed_at, self.effective_at)
            or self.expires_at <= self.available_at
        ):
            raise ValueError(
                "availability must follow observation/effectiveness; "
                "expiry must follow availability"
            )
        return self


class MarketDataRequest(MarketDto):
    instrument_id: UUID
    source: Text
    source_name: Text
    as_of: AwareDatetime
    base_currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] = "CNY"
    portfolio_id: UUID | None = None

    @field_validator("as_of")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class QuoteProvenance(MarketDto):
    instrument_id: UUID
    evidence_id: UUID
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: Literal["MANUAL_MARKET"] = "MANUAL_MARKET"
    source_name: str
    source_locator: str
    currency: str
    observed_at: AwareDatetime
    effective_at: AwareDatetime
    available_at: AwareDatetime
    ingested_at: AwareDatetime
    expires_at: AwareDatetime
    independently_verified: Literal[False] = False
    trading_grade: Literal[False] = False


class MarketQuote(MarketDto):
    price: Decimal
    provenance: QuoteProvenance

    @field_validator("price", mode="before")
    @classmethod
    def exact_price(cls, value: Decimal | str | int) -> Decimal:
        result = exact_decimal(value)
        if result <= 0:
            raise ValueError("quote price must be positive")
        return result


class MarketDataSnapshot(MarketDto):
    schema_version: Literal["1.0"] = "1.0"
    instrument_id: UUID
    source: str
    source_name: str
    as_of: AwareDatetime
    base_currency: str
    status: QuoteStatus
    reason_code: str
    quote: MarketQuote | None = None
    provenance: QuoteProvenance | None = None

    @model_validator(mode="after")
    def quote_only_when_available(self) -> Self:
        if (self.status == "AVAILABLE") != (self.quote is not None):
            raise ValueError("only available snapshots carry a reference price")
        if self.quote and self.quote.provenance != self.provenance:
            raise ValueError("quote and snapshot provenance must match")
        return self


def unavailable(request: MarketDataRequest, status: QuoteStatus, reason: str) -> MarketDataSnapshot:
    return MarketDataSnapshot(
        **request.model_dump(exclude={"portfolio_id"}), status=status, reason_code=reason
    )


class ManualQuoteSaved(MarketDto):
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID
    evidence_id: UUID
    content_hash: str
    ingested_at: AwareDatetime


class MarketDataCapabilities(MarketDto):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    supported_sources: tuple[Literal["MANUAL_MARKET"], ...]
    currency_boundary: Literal["CNY_ONLY"] = "CNY_ONLY"
    fx_supported: Literal[False] = False
    universe_supported: Literal[False] = False
    historical_bars_supported: Literal[False] = False
    trading_grade: Literal[False] = False
    automatic_network_calls: Literal[False] = False


class MarketDataPort(Protocol):
    async def get_snapshot(self, request: MarketDataRequest) -> MarketDataSnapshot: ...


class ManualMarketWriterPort(Protocol):
    async def save_quote(self, command: ManualQuoteInput) -> ManualQuoteSaved: ...


class MarketDataService:
    def __init__(
        self,
        ports: Mapping[str, MarketDataPort],
        writer: ManualMarketWriterPort,
        catalog: InstrumentCatalogService,
        portfolios: PortfolioBookService,
        *,
        now: Callable[[], datetime] | None = None,
    ):
        self._ports = MappingProxyType(dict(ports))
        self._writer = writer
        self._catalog = catalog
        self._portfolios = portfolios
        self._now = now or (lambda: datetime.now(UTC))

    async def get_instrument(self, instrument_id: UUID) -> InstrumentCatalogEntry:
        return await self._catalog.get(instrument_id)

    async def save_quote(self, command: ManualQuoteInput) -> ManualQuoteSaved:
        if command.currency != "CNY":
            raise MarketDataError("FX_REQUIRED")
        return await self._writer.save_quote(command)

    async def get_snapshot(self, request: MarketDataRequest) -> MarketDataSnapshot:
        if request.as_of > self._now():
            return unavailable(request, "NOT_YET_AVAILABLE", "FUTURE_AS_OF_NOT_ALLOWED")
        if request.base_currency != "CNY":
            return unavailable(request, "FX_REQUIRED", "FX_INPUT_NOT_AVAILABLE")
        instrument = await self._catalog.get(request.instrument_id)
        if instrument.currency != "CNY":
            return unavailable(request, "FX_REQUIRED", "INSTRUMENT_CURRENCY_REQUIRES_FX")
        if request.portfolio_id:
            portfolio = await self._portfolios.get_portfolio(request.portfolio_id)
            if portfolio.base_currency != "CNY" or any(
                p.currency != "CNY" and (p.core_quantity != 0 or p.tactical_quantity != 0)
                for p in portfolio.positions
            ):
                return unavailable(request, "FX_REQUIRED", "PORTFOLIO_CURRENCY_REQUIRES_FX")
        port = self._ports.get(request.source)
        if port is None:
            return unavailable(request, "UNSUPPORTED_SOURCE", "EXPLICIT_SOURCE_NOT_SUPPORTED")
        result = await port.get_snapshot(request)
        if (
            result.instrument_id,
            result.source,
            result.source_name,
            result.as_of,
            result.base_currency,
        ) != (
            request.instrument_id,
            request.source,
            request.source_name,
            request.as_of,
            request.base_currency,
        ):
            raise MarketDataError("MARKET_RESPONSE_MISMATCH")
        if result.provenance and (
            result.provenance.instrument_id != request.instrument_id
            or result.provenance.source != request.source
            or result.provenance.source_name != request.source_name
            or result.provenance.currency != request.base_currency
        ):
            raise MarketDataError("MARKET_RESPONSE_MISMATCH")
        if result.status == "AVAILABLE" and result.provenance:
            provenance = result.provenance
            if (
                max(
                    provenance.observed_at,
                    provenance.effective_at,
                    provenance.available_at,
                    provenance.ingested_at,
                )
                > request.as_of
                or provenance.expires_at <= request.as_of
            ):
                raise MarketDataError("MARKET_RESPONSE_TIME_INVALID")
        return result
