"""SQL adapters for PRODUCT-05 instrument catalog, portfolio book, and watchlist."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.instrument_catalog import (
    InstrumentCatalogEntry,
    InstrumentCatalogPort,
)
from investment_os.application.portfolio_book import (
    PortfolioBookPort,
    PortfolioPositionView,
    PortfolioView,
)
from investment_os.application.watchlist import WatchlistItemView, WatchlistPort
from investment_os.domain.instrument import InstrumentIdentity
from investment_os.infrastructure.persistence.models import (
    InstrumentRecord,
    PortfolioRecord,
    PositionRecord,
    WatchlistItemRecord,
)


def _catalog_entry(record: InstrumentRecord) -> InstrumentCatalogEntry:
    return InstrumentCatalogEntry(
        instrument_id=record.id,
        market=record.exchange,
        symbol=record.symbol,
        name=record.name,
        asset_type=record.asset_type,
        currency=record.currency,
        sector=record.sector,
    )


class SqlInstrumentCatalogAdapter(InstrumentCatalogPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, identity: InstrumentIdentity) -> InstrumentCatalogEntry:
        statement = select(InstrumentRecord).where(
            InstrumentRecord.symbol == identity.symbol,
            InstrumentRecord.exchange == identity.market,
        )
        record = (await self._session.scalars(statement)).one_or_none()
        if record is None:
            record = InstrumentRecord(
                id=uuid4(),
                symbol=identity.symbol,
                exchange=identity.market,
                name=identity.name,
                asset_type=identity.asset_type,
                currency=identity.currency,
                sector=identity.sector,
                status="ACTIVE",
            )
            self._session.add(record)
        else:
            record.name = identity.name
            record.asset_type = identity.asset_type
            record.currency = identity.currency
            record.sector = identity.sector
        await self._session.flush()
        return _catalog_entry(record)

    async def get(self, instrument_id: UUID) -> InstrumentCatalogEntry | None:
        record = await self._session.get(InstrumentRecord, instrument_id)
        return None if record is None else _catalog_entry(record)

    async def find_by_natural_key(self, market: str, symbol: str) -> InstrumentCatalogEntry | None:
        statement = select(InstrumentRecord).where(
            InstrumentRecord.symbol == symbol,
            InstrumentRecord.exchange == market,
        )
        record = (await self._session.scalars(statement)).one_or_none()
        return None if record is None else _catalog_entry(record)

    async def search(self, query: str, *, limit: int = 20) -> tuple[InstrumentCatalogEntry, ...]:
        pattern = f"%{query.strip()}%"
        statement = (
            select(InstrumentRecord)
            .where(
                or_(
                    InstrumentRecord.symbol.ilike(pattern),
                    InstrumentRecord.name.ilike(pattern),
                    InstrumentRecord.exchange.ilike(pattern),
                )
            )
            .order_by(InstrumentRecord.symbol, InstrumentRecord.exchange)
            .limit(limit)
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(_catalog_entry(record) for record in records)


def _position_view(
    record: PositionRecord,
    instrument: InstrumentRecord,
) -> PortfolioPositionView:
    return PortfolioPositionView(
        position_id=record.id,
        instrument_id=record.instrument_id,
        market=instrument.exchange,
        symbol=instrument.symbol,
        name=instrument.name,
        asset_type=instrument.asset_type,
        currency=instrument.currency,
        sector=instrument.sector,
        core_quantity=record.core_quantity,
        tactical_quantity=record.tactical_quantity,
        average_cost=record.avg_cost,
    )


class SqlPortfolioBookAdapter(PortfolioBookPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_portfolio(
        self,
        *,
        name: str,
        base_currency: str,
        cash_balance: Decimal,
    ) -> UUID:
        record = PortfolioRecord(
            id=uuid4(),
            name=name,
            base_currency=base_currency,
            cash_balance=cash_balance,
            status="ACTIVE",
            policy_id=None,
        )
        self._session.add(record)
        await self._session.flush()
        return record.id

    async def get_portfolio(self, portfolio_id: UUID) -> PortfolioView | None:
        record = await self._session.get(PortfolioRecord, portfolio_id)
        if record is None:
            return None
        return await self._view(record)

    async def list_portfolios(self) -> tuple[PortfolioView, ...]:
        statement = select(PortfolioRecord).order_by(PortfolioRecord.created_at, PortfolioRecord.id)
        records = (await self._session.scalars(statement)).all()
        views: list[PortfolioView] = []
        for record in records:
            views.append(await self._view(record))
        return tuple(views)

    async def _view(self, record: PortfolioRecord) -> PortfolioView:
        statement = (
            select(PositionRecord, InstrumentRecord)
            .join(InstrumentRecord, InstrumentRecord.id == PositionRecord.instrument_id)
            .where(PositionRecord.portfolio_id == record.id)
            .order_by(InstrumentRecord.symbol, InstrumentRecord.exchange)
        )
        rows = (await self._session.execute(statement)).all()
        positions = tuple(_position_view(position, instrument) for position, instrument in rows)
        return PortfolioView(
            portfolio_id=record.id,
            name=record.name,
            base_currency=record.base_currency,
            cash_balance=record.cash_balance,
            status=record.status,
            positions=positions,
        )

    async def upsert_position(
        self,
        *,
        portfolio_id: UUID,
        instrument_id: UUID,
        core_quantity: Decimal,
        tactical_quantity: Decimal,
        average_cost: Decimal,
    ) -> PortfolioPositionView:
        statement = select(PositionRecord).where(
            PositionRecord.portfolio_id == portfolio_id,
            PositionRecord.instrument_id == instrument_id,
        )
        record = (await self._session.scalars(statement)).one_or_none()
        if record is None:
            record = PositionRecord(
                id=uuid4(),
                portfolio_id=portfolio_id,
                instrument_id=instrument_id,
                core_quantity=core_quantity,
                tactical_quantity=tactical_quantity,
                avg_cost=average_cost,
                realized_pnl=Decimal("0"),
                version=1,
            )
            self._session.add(record)
        else:
            record.core_quantity = core_quantity
            record.tactical_quantity = tactical_quantity
            record.avg_cost = average_cost
            record.version = record.version + 1
        await self._session.flush()
        instrument = await self._session.get(InstrumentRecord, instrument_id)
        if instrument is None:
            raise RuntimeError("instrument disappeared while writing position")
        return _position_view(record, instrument)

    async def set_cash_balance(self, portfolio_id: UUID, cash_balance: Decimal) -> PortfolioView:
        record = await self._session.get(PortfolioRecord, portfolio_id)
        if record is None:
            raise RuntimeError("portfolio disappeared while writing cash")
        record.cash_balance = cash_balance
        await self._session.flush()
        return await self._view(record)


class SqlWatchlistAdapter(WatchlistPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, *, instrument_id: UUID, added_at: datetime) -> WatchlistItemView:
        record = WatchlistItemRecord(
            id=uuid4(),
            instrument_id=instrument_id,
            added_at=added_at,
        )
        self._session.add(record)
        await self._session.flush()
        return await self._item_view(record)

    async def remove(self, *, instrument_id: UUID) -> bool:
        statement = delete(WatchlistItemRecord).where(
            WatchlistItemRecord.instrument_id == instrument_id
        )
        result = await self._session.execute(statement)
        await self._session.flush()
        deleted = getattr(result, "rowcount", 0) or 0
        return int(deleted) > 0

    async def list_items(self) -> tuple[WatchlistItemView, ...]:
        statement = (
            select(WatchlistItemRecord, InstrumentRecord)
            .join(InstrumentRecord, InstrumentRecord.id == WatchlistItemRecord.instrument_id)
            .order_by(WatchlistItemRecord.added_at, InstrumentRecord.symbol)
        )
        rows = (await self._session.execute(statement)).all()
        views: list[WatchlistItemView] = []
        for record, instrument in rows:
            views.append(self._view(record, instrument))
        return tuple(views)

    async def contains(self, instrument_id: UUID) -> bool:
        statement = (
            select(func.count())
            .select_from(WatchlistItemRecord)
            .where(WatchlistItemRecord.instrument_id == instrument_id)
        )
        count = (await self._session.execute(statement)).scalar_one()
        return int(count) > 0

    async def _item_view(self, record: WatchlistItemRecord) -> WatchlistItemView:
        instrument = await self._session.get(InstrumentRecord, record.instrument_id)
        if instrument is None:
            raise RuntimeError("instrument disappeared from watchlist")
        return self._view(record, instrument)

    def _view(self, record: WatchlistItemRecord, instrument: InstrumentRecord) -> WatchlistItemView:
        # PRODUCT-05 product fields: never fabricate lifecycle/thesis/freshness/monitoring.
        return WatchlistItemView(
            watchlist_item_id=record.id,
            instrument_id=record.instrument_id,
            market=instrument.exchange,
            symbol=instrument.symbol,
            name=instrument.name,
            asset_type=instrument.asset_type,
            currency=instrument.currency,
            sector=instrument.sector,
            added_at=record.added_at
            if record.added_at.tzinfo
            else record.added_at.replace(tzinfo=UTC),
            lifecycle_state=None,
            thesis_state=None,
            data_freshness_as_of=None,
            next_monitoring_condition=None,
        )


class SessionCatalogPort:
    """Session-factory adapter so API/services can use one process-wide factory."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert(self, identity: InstrumentIdentity) -> InstrumentCatalogEntry:
        async with self._session_factory() as session:
            entry = await SqlInstrumentCatalogAdapter(session).upsert(identity)
            await session.commit()
            return entry

    async def get(self, instrument_id: UUID) -> InstrumentCatalogEntry | None:
        async with self._session_factory() as session:
            return await SqlInstrumentCatalogAdapter(session).get(instrument_id)

    async def find_by_natural_key(self, market: str, symbol: str) -> InstrumentCatalogEntry | None:
        async with self._session_factory() as session:
            return await SqlInstrumentCatalogAdapter(session).find_by_natural_key(market, symbol)

    async def search(self, query: str, *, limit: int = 20) -> tuple[InstrumentCatalogEntry, ...]:
        async with self._session_factory() as session:
            return await SqlInstrumentCatalogAdapter(session).search(query, limit=limit)


class SessionPortfolioBookPort:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_portfolio(
        self,
        *,
        name: str,
        base_currency: str,
        cash_balance: Decimal,
    ) -> UUID:
        async with self._session_factory() as session:
            portfolio_id = await SqlPortfolioBookAdapter(session).create_portfolio(
                name=name,
                base_currency=base_currency,
                cash_balance=cash_balance,
            )
            await session.commit()
            return portfolio_id

    async def get_portfolio(self, portfolio_id: UUID) -> PortfolioView | None:
        async with self._session_factory() as session:
            return await SqlPortfolioBookAdapter(session).get_portfolio(portfolio_id)

    async def list_portfolios(self) -> tuple[PortfolioView, ...]:
        async with self._session_factory() as session:
            return await SqlPortfolioBookAdapter(session).list_portfolios()

    async def upsert_position(
        self,
        *,
        portfolio_id: UUID,
        instrument_id: UUID,
        core_quantity: Decimal,
        tactical_quantity: Decimal,
        average_cost: Decimal,
    ) -> PortfolioPositionView:
        async with self._session_factory() as session:
            view = await SqlPortfolioBookAdapter(session).upsert_position(
                portfolio_id=portfolio_id,
                instrument_id=instrument_id,
                core_quantity=core_quantity,
                tactical_quantity=tactical_quantity,
                average_cost=average_cost,
            )
            await session.commit()
            return view

    async def set_cash_balance(self, portfolio_id: UUID, cash_balance: Decimal) -> PortfolioView:
        async with self._session_factory() as session:
            view = await SqlPortfolioBookAdapter(session).set_cash_balance(
                portfolio_id, cash_balance
            )
            await session.commit()
            return view


class SessionWatchlistPort:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, *, instrument_id: UUID, added_at: datetime) -> WatchlistItemView:
        async with self._session_factory() as session:
            view = await SqlWatchlistAdapter(session).add(
                instrument_id=instrument_id, added_at=added_at
            )
            await session.commit()
            return view

    async def remove(self, *, instrument_id: UUID) -> bool:
        async with self._session_factory() as session:
            removed = await SqlWatchlistAdapter(session).remove(instrument_id=instrument_id)
            await session.commit()
            return removed

    async def list_items(self) -> tuple[WatchlistItemView, ...]:
        async with self._session_factory() as session:
            return await SqlWatchlistAdapter(session).list_items()

    async def contains(self, instrument_id: UUID) -> bool:
        async with self._session_factory() as session:
            return await SqlWatchlistAdapter(session).contains(instrument_id)
