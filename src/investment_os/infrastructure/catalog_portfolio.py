"""SQL adapters for PRODUCT-05 instrument catalog, portfolio book, and watchlist."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
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
    AuditLogRecord,
    InstrumentRecord,
    PortfolioImportClaimRecord,
    PortfolioRecord,
    PositionRecord,
    WatchlistItemRecord,
)


def _audit_kwargs(actor: str = "product_portfolio") -> dict[str, object]:
    return {
        "created_by": actor,
        "correlation_id": uuid4(),
        "schema_version": "1.0",
        "metadata_json": {},
    }


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
                **_audit_kwargs("instrument_catalog"),
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
        core_average_cost=record.core_average_cost,
        tactical_average_cost=record.tactical_average_cost,
        core_reason=record.core_reason,
        tactical_reason=record.tactical_reason,
        operation=record.last_operation,
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
            **_audit_kwargs("portfolio_book"),
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
        core_average_cost: Decimal | None = None,
        tactical_average_cost: Decimal | None = None,
        core_reason: str = "",
        tactical_reason: str = "",
        operation: str = "MANUAL",
    ) -> PortfolioPositionView:
        resolved_core_avg = (
            core_average_cost
            if core_average_cost is not None
            else (average_cost if core_quantity != 0 else Decimal("0"))
        )
        resolved_tactical_avg = (
            tactical_average_cost
            if tactical_average_cost is not None
            else (average_cost if tactical_quantity != 0 else Decimal("0"))
        )
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
                core_average_cost=resolved_core_avg,
                tactical_average_cost=resolved_tactical_avg,
                core_reason=core_reason,
                tactical_reason=tactical_reason,
                last_operation=operation,
                realized_pnl=Decimal("0"),
                version=1,
                **_audit_kwargs("portfolio_book"),
            )
            self._session.add(record)
        else:
            record.core_quantity = core_quantity
            record.tactical_quantity = tactical_quantity
            record.avg_cost = average_cost
            record.core_average_cost = resolved_core_avg
            record.tactical_average_cost = resolved_tactical_avg
            record.core_reason = core_reason
            record.tactical_reason = tactical_reason
            record.last_operation = operation
            record.version = record.version + 1
        await self._session.flush()
        await self._emit_position_event(
            portfolio_id=portfolio_id,
            instrument_id=instrument_id,
            core_quantity=core_quantity,
            tactical_quantity=tactical_quantity,
            average_cost=average_cost,
            core_reason=core_reason,
            tactical_reason=tactical_reason,
            operation=operation,
        )
        instrument = await self._session.get(InstrumentRecord, instrument_id)
        if instrument is None:
            raise RuntimeError("instrument disappeared while writing position")
        return _position_view(record, instrument)

    async def _emit_position_event(
        self,
        *,
        portfolio_id: UUID,
        instrument_id: UUID,
        core_quantity: Decimal,
        tactical_quantity: Decimal,
        average_cost: Decimal,
        core_reason: str,
        tactical_reason: str,
        operation: str,
    ) -> None:
        from investment_os.infrastructure.persistence.models import (
            EventLogRecord,
            OutboxEventRecord,
        )

        correlation_id = uuid4()
        event = EventLogRecord(
            event_type="portfolio.position_upserted",
            aggregate_type="Portfolio",
            aggregate_id=portfolio_id,
            payload_json={
                "instrument_id": str(instrument_id),
                "core_quantity": str(core_quantity),
                "tactical_quantity": str(tactical_quantity),
                "average_cost": str(average_cost),
                "core_reason": core_reason,
                "tactical_reason": tactical_reason,
                "operation": operation,
            },
            occurred_at=datetime.now(UTC),
            correlation_id=correlation_id,
            causation_id=None,
            schema_version="1.0",
            metadata_json={},
            created_by="portfolio_book",
        )
        self._session.add(event)
        await self._session.flush()
        self._session.add(
            OutboxEventRecord(
                event_id=event.id,
                topic="portfolio.position_upserted",
                payload_json={"event_id": str(event.id), "portfolio_id": str(portfolio_id)},
                published_at=None,
                attempts=0,
                last_error=None,
                correlation_id=correlation_id,
                causation_id=event.id,
                schema_version="1.0",
                metadata_json={},
                created_by="portfolio_book",
            )
        )

    async def set_cash_balance(self, portfolio_id: UUID, cash_balance: Decimal) -> PortfolioView:
        record = await self._session.get(PortfolioRecord, portfolio_id)
        if record is None:
            raise RuntimeError("portfolio disappeared while writing cash")
        record.cash_balance = cash_balance
        await self._session.flush()
        return await self._view(record)

    async def record_import_audit(
        self,
        *,
        portfolio_id: UUID,
        conflict_policy: str,
        applied: tuple[object, ...],
        import_hash: str = "",
    ) -> UUID:
        return await self._write_import_audit(
            portfolio_id=portfolio_id,
            conflict_policy=conflict_policy,
            applied=applied,
            import_hash=import_hash,
        )

    async def find_import_audit(
        self,
        *,
        portfolio_id: UUID,
        import_hash: str,
    ) -> UUID | None:
        statement = select(PortfolioImportClaimRecord.audit_id).where(
            PortfolioImportClaimRecord.portfolio_id == portfolio_id,
            PortfolioImportClaimRecord.import_hash == import_hash,
        )
        return (await self._session.scalars(statement)).first()

    async def list_import_audits(
        self,
        *,
        portfolio_id: UUID,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        statement = (
            select(PortfolioImportClaimRecord, AuditLogRecord)
            .join(AuditLogRecord, AuditLogRecord.id == PortfolioImportClaimRecord.audit_id)
            .where(PortfolioImportClaimRecord.portfolio_id == portfolio_id)
            .order_by(PortfolioImportClaimRecord.created_at.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        results: list[dict[str, object]] = []
        for claim, audit in rows:
            applied = (audit.metadata_json or {}).get("applied", [])
            results.append(
                {
                    "audit_id": str(claim.audit_id),
                    "import_hash": claim.import_hash,
                    "conflict_policy": claim.conflict_policy,
                    "created_at": claim.created_at.isoformat(),
                    "applied": applied,
                }
            )
        return results

    async def apply_import_batch(
        self,
        *,
        portfolio_id: UUID,
        import_hash: str,
        conflict_policy: str,
        items: tuple[dict[str, object], ...],
        applied: tuple[object, ...],
    ) -> UUID:
        from sqlalchemy.exc import IntegrityError

        existing = await self.find_import_audit(portfolio_id=portfolio_id, import_hash=import_hash)
        if existing is not None:
            raise ApplicationError(
                ApplicationErrorCode.IDEMPOTENCY_KEY_CONFLICT,
                "相同 CSV 与冲突策略已导入过; 请勿重复确认",
                details={"audit_id": str(existing), "import_hash": import_hash},
            )

        audit_id = uuid4()
        catalog = SqlInstrumentCatalogAdapter(self._session)
        for item in items:
            identity = item["identity"]
            assert isinstance(identity, InstrumentIdentity)
            entry = await catalog.upsert(identity)
            await self.upsert_position(
                portfolio_id=portfolio_id,
                instrument_id=entry.instrument_id,
                core_quantity=item["core_quantity"],  # type: ignore[arg-type]
                tactical_quantity=item["tactical_quantity"],  # type: ignore[arg-type]
                average_cost=item["average_cost"],  # type: ignore[arg-type]
            )

        claim = PortfolioImportClaimRecord(
            id=uuid4(),
            portfolio_id=portfolio_id,
            import_hash=import_hash,
            audit_id=audit_id,
            conflict_policy=conflict_policy,
            created_by="product_portfolio",
        )
        self._session.add(claim)
        await self._write_import_audit(
            portfolio_id=portfolio_id,
            conflict_policy=conflict_policy,
            applied=applied,
            import_hash=import_hash,
            audit_id=audit_id,
        )
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ApplicationError(
                ApplicationErrorCode.IDEMPOTENCY_KEY_CONFLICT,
                "相同 CSV 与冲突策略已导入过; 请勿重复确认",
                details={"import_hash": import_hash},
            ) from exc
        return audit_id

    async def _write_import_audit(
        self,
        *,
        portfolio_id: UUID,
        conflict_policy: str,
        applied: tuple[object, ...],
        import_hash: str,
        audit_id: UUID | None = None,
        positions: tuple[tuple[UUID, Decimal, Decimal, Decimal], ...] | None = None,
    ) -> UUID:
        if audit_id is None:
            audit_id = uuid4()
        payload = []
        for item in applied:
            payload.append(
                {
                    "line_number": getattr(item, "line_number", None),
                    "market": getattr(item, "market", None),
                    "symbol": getattr(item, "symbol", None),
                    "action": getattr(item, "action", None),
                    "before": getattr(item, "before", None),
                    "after": getattr(item, "after", None),
                }
            )
        record = AuditLogRecord(
            id=audit_id,
            actor_type="USER",
            actor_id="product_portfolio",
            operation="portfolio_csv_import",
            entity_type="portfolio",
            entity_id=portfolio_id,
            ip_or_runtime_ref="local-product-ui",
            occurred_at=datetime.now(UTC),
            correlation_id=uuid4(),
            created_by="product_portfolio",
            metadata_json={
                "conflict_policy": conflict_policy,
                "import_hash": import_hash,
                "applied": payload,
                "positions": (
                    [
                        {
                            "instrument_id": str(item[0]),
                            "core_quantity": str(item[1]),
                            "tactical_quantity": str(item[2]),
                            "average_cost": str(item[3]),
                        }
                        for item in positions
                    ]
                    if positions is not None
                    else []
                ),
            },
        )
        self._session.add(record)
        await self._session.flush()
        return audit_id


class SqlWatchlistAdapter(WatchlistPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, *, instrument_id: UUID, added_at: datetime) -> WatchlistItemView:
        record = WatchlistItemRecord(
            id=uuid4(),
            instrument_id=instrument_id,
            added_at=added_at,
            **_audit_kwargs("watchlist"),
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
        core_average_cost: Decimal | None = None,
        tactical_average_cost: Decimal | None = None,
        core_reason: str = "",
        tactical_reason: str = "",
        operation: str = "MANUAL",
    ) -> PortfolioPositionView:
        async with self._session_factory() as session:
            view = await SqlPortfolioBookAdapter(session).upsert_position(
                portfolio_id=portfolio_id,
                instrument_id=instrument_id,
                core_quantity=core_quantity,
                tactical_quantity=tactical_quantity,
                average_cost=average_cost,
                core_average_cost=core_average_cost,
                tactical_average_cost=tactical_average_cost,
                core_reason=core_reason,
                tactical_reason=tactical_reason,
                operation=operation,
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

    async def record_import_audit(
        self,
        *,
        portfolio_id: UUID,
        conflict_policy: str,
        applied: tuple[object, ...],
        import_hash: str = "",
    ) -> UUID:
        async with self._session_factory() as session:
            adapter = SqlPortfolioBookAdapter(session)
            audit_id = await adapter.record_import_audit(
                portfolio_id=portfolio_id,
                conflict_policy=conflict_policy,
                applied=applied,
                import_hash=import_hash,
            )
            await session.commit()
            return audit_id

    async def find_import_audit(
        self,
        *,
        portfolio_id: UUID,
        import_hash: str,
    ) -> UUID | None:
        async with self._session_factory() as session:
            return await SqlPortfolioBookAdapter(session).find_import_audit(
                portfolio_id=portfolio_id, import_hash=import_hash
            )

    async def list_import_audits(
        self,
        *,
        portfolio_id: UUID,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        async with self._session_factory() as session:
            return await SqlPortfolioBookAdapter(session).list_import_audits(
                portfolio_id=portfolio_id, limit=limit
            )

    async def apply_import_batch(
        self,
        *,
        portfolio_id: UUID,
        import_hash: str,
        conflict_policy: str,
        items: tuple[dict[str, object], ...],
        applied: tuple[object, ...],
    ) -> UUID:
        async with self._session_factory() as session:
            adapter = SqlPortfolioBookAdapter(session)
            audit_id = await adapter.apply_import_batch(
                portfolio_id=portfolio_id,
                import_hash=import_hash,
                conflict_policy=conflict_policy,
                items=items,
                applied=applied,
            )
            await session.commit()
            return audit_id


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
