"""PRODUCT-05 integration: catalog, portfolio book, watchlist, CSV import."""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from investment_os.application.instrument_catalog import InstrumentCatalogService
from investment_os.application.portfolio_book import (
    PortfolioBookService,
    PortfolioPositionInput,
)
from investment_os.application.portfolio_csv import PortfolioCsvImportService
from investment_os.application.watchlist import WatchlistService
from investment_os.domain.instrument import InstrumentIdentity
from investment_os.infrastructure.catalog_portfolio import (
    SessionCatalogPort,
    SessionPortfolioBookPort,
    SessionWatchlistPort,
)

CSV_HEADER = (
    "market,symbol,name,asset_type,currency,sector,core_quantity,tactical_quantity,average_cost"
)


def _services(database_engine: AsyncEngine):
    factory = async_sessionmaker(database_engine, expire_on_commit=False, class_=AsyncSession)
    catalog_port = SessionCatalogPort(factory)
    catalog = InstrumentCatalogService(catalog_port)
    book = PortfolioBookService(SessionPortfolioBookPort(factory), catalog_port)
    watchlist = WatchlistService(SessionWatchlistPort(factory), catalog_port)
    csv_service = PortfolioCsvImportService(book)
    return catalog, book, watchlist, csv_service


async def test_catalog_search_and_portfolio_core_tactical_roundtrip(
    database_engine: AsyncEngine,
) -> None:
    catalog, book, _watchlist, _csv = _services(database_engine)

    identity = InstrumentIdentity(
        market=" sse ",
        symbol=" 600519 ",
        name="贵州茅台",
        asset_type="equity",
        currency="cny",
        sector="Consumer",
    )
    entry = await catalog.register(identity)
    assert entry.market == "SSE"
    assert entry.symbol == "600519"

    found = await catalog.search("600519")
    assert found and found[0].instrument_id == entry.instrument_id

    portfolio = await book.create_portfolio(
        name="个人组合", base_currency="cny", cash_balance=Decimal("100000")
    )
    assert portfolio.base_currency == "CNY"
    assert portfolio.cash_balance == Decimal("100000")

    updated = await book.record_manual_position(
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
    assert len(updated.positions) == 1
    assert updated.positions[0].core_quantity == Decimal("10")
    assert updated.positions[0].tactical_quantity == Decimal("2")

    reloaded = await book.get_portfolio(portfolio.portfolio_id)
    assert reloaded.positions[0].average_cost == Decimal("1600")


async def test_watchlist_add_remove_and_missing_fields_are_null(
    database_engine: AsyncEngine,
) -> None:
    _catalog, _book, watchlist, _csv = _services(database_engine)
    identity = InstrumentIdentity(
        market="SZSE",
        symbol="000001",
        name="平安银行",
        asset_type="EQUITY",
        currency="CNY",
        sector="Financials",
    )
    first = await watchlist.add_instrument(identity)
    second = await watchlist.add_instrument(identity)
    assert first.instrument_id == second.instrument_id
    assert first.lifecycle_state is None
    assert first.thesis_state is None
    assert first.data_freshness_as_of is None
    assert first.next_monitoring_condition is None

    items = await watchlist.list_items()
    assert len(items) == 1
    assert await watchlist.remove_instrument(market="SZSE", symbol="000001") is True
    assert await watchlist.list_items() == ()


async def test_csv_preview_then_confirm_imports_and_reconciles(
    database_engine: AsyncEngine,
) -> None:
    _catalog, book, _watchlist, csv_service = _services(database_engine)
    portfolio = await book.create_portfolio(
        name="csv-portfolio", base_currency="CNY", cash_balance=Decimal("0")
    )

    dirty = "\n".join(
        [
            CSV_HEADER,
            "SSE,600519,贵州茅台,EQUITY,CNY,Consumer,10,2,1600",
            "SSE,600519,贵州茅台,EQUITY,CNY,Consumer,x,2,1600",
        ]
    )
    preview = await csv_service.preview(portfolio.portfolio_id, dirty)
    assert preview.can_commit is False
    assert len(preview.invalid) == 1

    clean = "\n".join(
        [
            CSV_HEADER,
            "SSE,600519,贵州茅台,EQUITY,CNY,Consumer,10,2,1600",
            "SZSE,000001,平安银行,EQUITY,CNY,Financials,100,0,12.5",
        ]
    )
    result = await csv_service.confirm(portfolio_id=portfolio.portfolio_id, raw_text=clean)
    assert result.imported_count == 2
    assert len(result.portfolio.positions) == 2
    symbols = {position.symbol for position in result.portfolio.positions}
    assert symbols == {"600519", "000001"}
