"""PRODUCT-05 portfolio book and watchlist application tests."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.instrument_catalog import (
    InstrumentCatalogEntry,
)
from investment_os.application.portfolio_book import (
    PortfolioBookService,
    PortfolioPositionInput,
    PortfolioPositionView,
    PortfolioView,
)
from investment_os.application.watchlist import WatchlistItemView, WatchlistService
from investment_os.domain.instrument import InstrumentIdentity


class InMemoryCatalog:
    def __init__(self) -> None:
        self.entries: dict[tuple[str, str], InstrumentCatalogEntry] = {}

    async def upsert(self, identity: InstrumentIdentity) -> InstrumentCatalogEntry:
        key = identity.natural_key
        existing = self.entries.get(key)
        entry = InstrumentCatalogEntry(
            instrument_id=existing.instrument_id if existing else uuid4(),
            market=identity.market,
            symbol=identity.symbol,
            name=identity.name,
            asset_type=identity.asset_type,
            currency=identity.currency,
            sector=identity.sector,
        )
        self.entries[key] = entry
        return entry

    async def get(self, instrument_id):
        for entry in self.entries.values():
            if entry.instrument_id == instrument_id:
                return entry
        return None

    async def find_by_natural_key(self, market: str, symbol: str):
        return self.entries.get((market, symbol))

    async def search(self, query: str, *, limit: int = 20):
        return tuple(list(self.entries.values())[:limit])


class InMemoryPortfolios:
    def __init__(self) -> None:
        self.portfolios: dict[UUID, PortfolioView] = {}
        self.positions: dict[tuple[UUID, UUID], PortfolioPositionView] = {}

    async def create_portfolio(self, *, name, base_currency, cash_balance):
        from uuid import uuid4 as _uuid4

        portfolio_id = _uuid4()
        self.portfolios[portfolio_id] = PortfolioView(
            portfolio_id=portfolio_id,
            name=name,
            base_currency=base_currency,
            cash_balance=cash_balance,
            status="ACTIVE",
            positions=(),
        )
        return portfolio_id

    async def get_portfolio(self, portfolio_id):
        view = self.portfolios.get(portfolio_id)
        if view is None:
            return None
        positions = tuple(
            position for (pid, _), position in self.positions.items() if pid == portfolio_id
        )
        return PortfolioView(
            portfolio_id=view.portfolio_id,
            name=view.name,
            base_currency=view.base_currency,
            cash_balance=view.cash_balance,
            status=view.status,
            positions=positions,
        )

    async def list_portfolios(self):
        views = [await self.get_portfolio(pid) for pid in self.portfolios]
        return tuple(v for v in views if v is not None)

    async def upsert_position(
        self, *, portfolio_id, instrument_id, core_quantity, tactical_quantity, average_cost
    ):
        view = PortfolioPositionView(
            position_id=uuid4(),
            instrument_id=instrument_id,
            market="SSE",
            symbol="TEST",
            name="TEST",
            asset_type="EQUITY",
            currency="CNY",
            sector="",
            core_quantity=core_quantity,
            tactical_quantity=tactical_quantity,
            average_cost=average_cost,
        )
        self.positions[(portfolio_id, instrument_id)] = view
        return view

    async def set_cash_balance(self, portfolio_id, cash_balance):
        view = self.portfolios[portfolio_id]
        updated = PortfolioView(
            portfolio_id=view.portfolio_id,
            name=view.name,
            base_currency=view.base_currency,
            cash_balance=cash_balance,
            status=view.status,
            positions=(),
        )
        self.portfolios[portfolio_id] = updated
        return updated


class InMemoryWatchlist:
    def __init__(self) -> None:
        self.items: dict[UUID, WatchlistItemView] = {}

    async def add(self, *, instrument_id, added_at):
        view = WatchlistItemView(
            watchlist_item_id=uuid4(),
            instrument_id=instrument_id,
            market="SSE",
            symbol="600519",
            name="贵州茅台",
            asset_type="EQUITY",
            currency="CNY",
            sector="",
            added_at=added_at,
            lifecycle_state=None,
            thesis_state=None,
            data_freshness_as_of=None,
            next_monitoring_condition=None,
        )
        self.items[instrument_id] = view
        return view

    async def remove(self, *, instrument_id):
        return self.items.pop(instrument_id, None) is not None

    async def list_items(self):
        return tuple(self.items.values())

    async def contains(self, instrument_id):
        return instrument_id in self.items


def _identity() -> InstrumentIdentity:
    return InstrumentIdentity(
        market="SSE",
        symbol="600519",
        name="贵州茅台",
        asset_type="EQUITY",
        currency="CNY",
        sector="Consumer",
    )


@pytest.mark.asyncio
async def test_create_portfolio_and_manual_core_tactical_position() -> None:
    catalog = InMemoryCatalog()
    service = PortfolioBookService(InMemoryPortfolios(), catalog)
    portfolio = await service.create_portfolio(
        name="个人组合", base_currency="cny", cash_balance=Decimal("100000")
    )
    assert portfolio.base_currency == "CNY"
    assert portfolio.cash_balance == Decimal("100000")

    updated = await service.record_manual_position(
        portfolio_id=portfolio.portfolio_id,
        position=PortfolioPositionInput(
            market="SSE",
            symbol="600519",
            name="贵州茅台",
            asset_type="EQUITY",
            currency="CNY",
            sector="Consumer",
            core_quantity=Decimal("10"),
            tactical_quantity=Decimal("2"),
            average_cost=Decimal("1600"),
        ),
    )
    assert updated.positions[0].core_quantity == Decimal("10")
    assert updated.positions[0].tactical_quantity == Decimal("2")


@pytest.mark.asyncio
async def test_manual_position_rejects_float_average_cost() -> None:
    catalog = InMemoryCatalog()
    service = PortfolioBookService(InMemoryPortfolios(), catalog)
    portfolio = await service.create_portfolio(
        name="p", base_currency="USD", cash_balance=Decimal("0")
    )
    with pytest.raises(ApplicationError) as exc:
        await service.record_manual_position(
            portfolio_id=portfolio.portfolio_id,
            position=PortfolioPositionInput(
                market="NASDAQ",
                symbol="AAPL",
                name="Apple",
                asset_type="EQUITY",
                currency="USD",
                sector="Tech",
                core_quantity=Decimal("1"),
                tactical_quantity=Decimal("0"),
                average_cost=1.5,  # float must fail closed
            ),
        )
    assert exc.value.code is ApplicationErrorCode.PORTFOLIO_WRITE_INVALID


@pytest.mark.asyncio
async def test_watchlist_add_is_idempotent_and_missing_fields_are_none() -> None:
    catalog = InMemoryCatalog()
    watchlist = InMemoryWatchlist()
    service = WatchlistService(watchlist, catalog)
    first = await service.add_instrument(_identity())
    second = await service.add_instrument(_identity())
    assert first.instrument_id == second.instrument_id
    assert first.lifecycle_state is None
    assert first.thesis_state is None
    assert first.data_freshness_as_of is None
    assert first.next_monitoring_condition is None
    assert len(await service.list_items()) == 1


@pytest.mark.asyncio
async def test_watchlist_remove_unknown_returns_false() -> None:
    catalog = InMemoryCatalog()
    service = WatchlistService(InMemoryWatchlist(), catalog)
    assert await service.remove_instrument(market="SSE", symbol="NOPE") is False
