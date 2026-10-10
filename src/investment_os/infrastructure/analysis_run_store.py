"""SQL adapter for AnalysisRun persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.analysis_run import AnalysisRunPort, AnalysisRunRead
from investment_os.infrastructure.persistence.models import AnalysisRunRecord


def _read(record: AnalysisRunRecord) -> AnalysisRunRead:
    return AnalysisRunRead(
        id=record.id,
        instrument_id=record.instrument_id,
        portfolio_id=record.portfolio_id,
        source=record.source,
        status=record.status,
        as_of=record.as_of,
        policy_version_label=record.policy_version_label,
        failure_code=record.failure_code,
        failure_detail=record.failure_detail,
        payload=dict(record.payload_json or {}),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


class SqlAnalysisRunAdapter(AnalysisRunPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        instrument_id: UUID,
        portfolio_id: UUID,
        source: str,
        as_of: datetime,
        policy_version_label: str,
        status: str,
        payload: dict[str, Any],
        failure_code: str | None = None,
        failure_detail: str | None = None,
    ) -> UUID:
        record = AnalysisRunRecord(
            id=uuid4(),
            instrument_id=instrument_id,
            portfolio_id=portfolio_id,
            source=source,
            status=status,
            as_of=as_of,
            policy_version_label=policy_version_label,
            failure_code=failure_code,
            failure_detail=failure_detail,
            payload_json=payload,
            created_by="product_ui",
        )
        self._session.add(record)
        await self._session.flush()
        return record.id

    async def get(self, run_id: UUID) -> AnalysisRunRead | None:
        record = await self._session.get(AnalysisRunRecord, run_id)
        return None if record is None else _read(record)

    async def list_for_portfolio(
        self, *, portfolio_id: UUID, limit: int = 20
    ) -> tuple[AnalysisRunRead, ...]:
        statement = (
            select(AnalysisRunRecord)
            .where(AnalysisRunRecord.portfolio_id == portfolio_id)
            .order_by(AnalysisRunRecord.created_at.desc())
            .limit(limit)
        )
        return tuple(_read(row) for row in (await self._session.scalars(statement)).all())

    async def list_for_instrument(
        self, *, instrument_id: UUID, limit: int = 20
    ) -> tuple[AnalysisRunRead, ...]:
        statement = (
            select(AnalysisRunRecord)
            .where(AnalysisRunRecord.instrument_id == instrument_id)
            .order_by(AnalysisRunRecord.created_at.desc())
            .limit(limit)
        )
        return tuple(_read(row) for row in (await self._session.scalars(statement)).all())


class SessionAnalysisRunPort(AnalysisRunPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, **kwargs: Any) -> UUID:
        async with self._session_factory() as session:
            adapter = SqlAnalysisRunAdapter(session)
            run_id = await adapter.create(**kwargs)
            await session.commit()
            return run_id

    async def get(self, run_id: UUID) -> AnalysisRunRead | None:
        async with self._session_factory() as session:
            return await SqlAnalysisRunAdapter(session).get(run_id)

    async def list_for_portfolio(
        self, *, portfolio_id: UUID, limit: int = 20
    ) -> tuple[AnalysisRunRead, ...]:
        async with self._session_factory() as session:
            return await SqlAnalysisRunAdapter(session).list_for_portfolio(
                portfolio_id=portfolio_id, limit=limit
            )

    async def list_for_instrument(
        self, *, instrument_id: UUID, limit: int = 20
    ) -> tuple[AnalysisRunRead, ...]:
        async with self._session_factory() as session:
            return await SqlAnalysisRunAdapter(session).list_for_instrument(
                instrument_id=instrument_id, limit=limit
            )
