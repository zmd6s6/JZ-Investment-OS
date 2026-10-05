"""Application boundary for portfolio bookkeeping and manual position entry."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID, uuid4

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.instrument_catalog import (
    InstrumentCatalogEntry,
    InstrumentCatalogPort,
)
from investment_os.domain.instrument import InstrumentIdentity
from investment_os.domain.values import PositionBuckets, Quantity, exact_decimal

BucketName = Literal["CORE", "TACTICAL"]


@dataclass(frozen=True, slots=True)
class PortfolioPositionInput:
    market: str
    symbol: str
    name: str
    asset_type: str
    currency: str
    sector: str
    core_quantity: Decimal
    tactical_quantity: Decimal
    average_cost: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioPositionView:
    position_id: UUID
    instrument_id: UUID
    market: str
    symbol: str
    name: str
    asset_type: str
    currency: str
    sector: str
    core_quantity: Decimal
    tactical_quantity: Decimal
    average_cost: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioView:
    portfolio_id: UUID
    name: str
    base_currency: str
    cash_balance: Decimal
    status: str
    positions: tuple[PortfolioPositionView, ...]


class PortfolioBookPort(Protocol):
    async def create_portfolio(
        self,
        *,
        name: str,
        base_currency: str,
        cash_balance: Decimal,
    ) -> UUID: ...

    async def get_portfolio(self, portfolio_id: UUID) -> PortfolioView | None: ...

    async def list_portfolios(self) -> tuple[PortfolioView, ...]: ...

    async def upsert_position(
        self,
        *,
        portfolio_id: UUID,
        instrument_id: UUID,
        core_quantity: Decimal,
        tactical_quantity: Decimal,
        average_cost: Decimal,
    ) -> PortfolioPositionView: ...

    async def set_cash_balance(
        self, portfolio_id: UUID, cash_balance: Decimal
    ) -> PortfolioView: ...

    async def record_import_audit(
        self,
        *,
        portfolio_id: UUID,
        conflict_policy: str,
        applied: tuple[object, ...],
    ) -> UUID: ...


class PortfolioBookService:
    """Manual portfolio bookkeeping for PRODUCT-05; no valuation or trading."""

    def __init__(
        self,
        portfolios: PortfolioBookPort,
        catalog: InstrumentCatalogPort,
    ) -> None:
        self._portfolios = portfolios
        self._catalog = catalog

    async def create_portfolio(
        self,
        *,
        name: str,
        base_currency: str,
        cash_balance: Decimal | str | int = Decimal("0"),
    ) -> PortfolioView:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
                "portfolio name must not be empty",
            )
        if len(cleaned_name) > 255:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
                "portfolio name must be at most 255 characters",
            )
        try:
            currency = base_currency.strip().upper()
        except AttributeError as exc:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
                "base currency must be a string",
            ) from exc
        if len(currency) != 3:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
                "base currency must be a 3-letter code",
            )
        try:
            cash = exact_decimal(cash_balance)
        except Exception as exc:  # domain errors are application-visible rejections
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
                "cash balance must be a valid non-float decimal",
            ) from exc
        if cash < 0:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
                "cash balance must not be negative",
            )
        portfolio_id = await self._portfolios.create_portfolio(
            name=cleaned_name,
            base_currency=currency,
            cash_balance=cash,
        )
        view = await self._portfolios.get_portfolio(portfolio_id)
        if view is None:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_NOT_FOUND,
                "portfolio disappeared after create",
                details={"portfolio_id": str(portfolio_id)},
            )
        return view

    async def get_portfolio(self, portfolio_id: UUID) -> PortfolioView:
        view = await self._portfolios.get_portfolio(portfolio_id)
        if view is None:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_NOT_FOUND,
                "portfolio was not found",
                details={"portfolio_id": str(portfolio_id)},
            )
        return view

    async def list_portfolios(self) -> tuple[PortfolioView, ...]:
        return await self._portfolios.list_portfolios()

    async def record_manual_position(
        self,
        *,
        portfolio_id: UUID,
        position: PortfolioPositionInput,
    ) -> PortfolioView:
        await self.get_portfolio(portfolio_id)
        try:
            identity = InstrumentIdentity(
                market=position.market,
                symbol=position.symbol,
                name=position.name,
                asset_type=position.asset_type,
                currency=position.currency,
                sector=position.sector,
            )
            core = Quantity(position.core_quantity)
            tactical = Quantity(position.tactical_quantity)
            buckets = PositionBuckets(
                core=core,
                tactical=tactical,
                total=Quantity(core.value + tactical.value),
            )
            average_cost = exact_decimal(position.average_cost)
        except Exception as exc:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
                "manual position input is invalid",
                details={"reason": str(exc)},
            ) from exc
        if average_cost < 0:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
                "average cost must not be negative",
            )
        if buckets.total.value == 0 and average_cost != 0:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
                "zero quantity cannot carry a non-zero average cost",
            )
        entry: InstrumentCatalogEntry = await self._catalog.upsert(identity)
        await self._portfolios.upsert_position(
            portfolio_id=portfolio_id,
            instrument_id=entry.instrument_id,
            core_quantity=buckets.core.value,
            tactical_quantity=buckets.tactical.value,
            average_cost=average_cost,
        )
        return await self.get_portfolio(portfolio_id)

    async def set_cash_balance(
        self, portfolio_id: UUID, cash_balance: Decimal | str | int
    ) -> PortfolioView:
        await self.get_portfolio(portfolio_id)
        try:
            cash = exact_decimal(cash_balance)
        except Exception as exc:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
                "cash balance must be a valid non-float decimal",
            ) from exc
        if cash < 0:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
                "cash balance must not be negative",
            )
        return await self._portfolios.set_cash_balance(portfolio_id, cash)

    async def record_import_audit(
        self,
        *,
        portfolio_id: UUID,
        conflict_policy: str,
        applied: tuple[object, ...],
    ) -> UUID:
        return await self._portfolios.record_import_audit(
            portfolio_id=portfolio_id,
            conflict_policy=conflict_policy,
            applied=applied,
        )


def new_portfolio_id() -> UUID:
    return uuid4()
