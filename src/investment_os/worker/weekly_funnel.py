"""Compose only local SQL inputs; deliberately no research/model gateway dependency."""

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.instrument_catalog import InstrumentCatalogService
from investment_os.application.market_data import MarketDataService
from investment_os.application.opportunities import OpportunityService
from investment_os.application.portfolio_book import PortfolioBookService
from investment_os.infrastructure.catalog_portfolio import (
    SessionCatalogPort,
    SessionPortfolioBookPort,
)
from investment_os.infrastructure.manual_market_data import SqlManualMarketData
from investment_os.infrastructure.opportunities import LocalExplicitUniverse, SqlOpportunityStore
from investment_os.infrastructure.opportunity_schedule import WeeklyFunnelRunner
from investment_os.infrastructure.universe_snapshots import SqlUniverseSnapshots


def weekly_worker(
    sessions: async_sessionmaker[AsyncSession], *, now: Callable[[], datetime] | None = None
) -> WeeklyFunnelRunner:
    clock = now or (lambda: datetime.now(UTC))
    catalog_port = SessionCatalogPort(sessions)
    catalog = InstrumentCatalogService(catalog_port)
    quotes = SqlManualMarketData(sessions)
    market = MarketDataService(
        {"MANUAL_MARKET": quotes},
        quotes,
        catalog,
        PortfolioBookService(SessionPortfolioBookPort(sessions), catalog_port),
        now=clock,
    )
    store = SqlOpportunityStore(sessions, now=clock)
    service = OpportunityService(
        LocalExplicitUniverse(catalog),
        store,
        market,
        store,
        now=clock,
        scope_validator=SqlUniverseSnapshots(sessions),
    )
    return WeeklyFunnelRunner(sessions, service)
