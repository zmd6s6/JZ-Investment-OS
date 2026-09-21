"""Persistent, non-sensitive first-run onboarding state."""

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from investment_os.application.onboarding import (
    OnboardingService,
    OnboardingState,
    OnboardingStatus,
)
from investment_os.infrastructure.persistence.models import (
    EventLogRecord,
    OutboxEventRecord,
    ProductOnboardingStateRecord,
)

ONBOARDING_STATE_ID = UUID("00000000-0000-0000-0000-000000000001")
ONBOARDING_STARTED_EVENT = "product_onboarding.started"
ONBOARDING_STARTED_TOPIC = "product.onboarding.started"


class SqlAlchemyOnboardingStore:
    """Store only progress for the supported setup flow, never credentials or portfolio content."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self) -> OnboardingState:
        async with self._session_factory() as session:
            record = await session.get(ProductOnboardingStateRecord, ONBOARDING_STATE_ID)
        if record is None:
            return OnboardingState(status="NOT_STARTED", started_at=None)
        return self._read_state(record)

    async def start(self) -> OnboardingState:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            record = await session.scalar(
                select(ProductOnboardingStateRecord)
                .where(ProductOnboardingStateRecord.id == ONBOARDING_STATE_ID)
                .with_for_update()
            )
            if record is None:
                record = ProductOnboardingStateRecord(
                    id=ONBOARDING_STATE_ID,
                    status="IN_PROGRESS",
                    started_at=now,
                )
                session.add(record)
                await self._record_start_event(session, now)
            elif record.status == "NOT_STARTED":
                record.status = "IN_PROGRESS"
                record.started_at = now
                record.updated_at = now
                await self._record_start_event(session, now)
            await session.commit()
            return self._read_state(record)

    @staticmethod
    def _read_state(record: ProductOnboardingStateRecord) -> OnboardingState:
        if record.status not in {"NOT_STARTED", "IN_PROGRESS"}:
            raise RuntimeError(
                "Persisted onboarding state is not supported by this application version"
            )
        return OnboardingState(
            status=cast(OnboardingStatus, record.status),
            started_at=record.started_at,
        )

    @staticmethod
    async def _record_start_event(session: AsyncSession, occurred_at: datetime) -> None:
        correlation_id = uuid4()
        event = EventLogRecord(
            event_type=ONBOARDING_STARTED_EVENT,
            aggregate_type="ProductOnboardingState",
            aggregate_id=ONBOARDING_STATE_ID,
            payload_json={"status": "IN_PROGRESS"},
            occurred_at=occurred_at,
            correlation_id=correlation_id,
            causation_id=None,
            schema_version="1.0",
            metadata_json={},
            created_by="product_onboarding",
        )
        session.add(event)
        await session.flush()
        session.add(
            OutboxEventRecord(
                event_id=event.id,
                topic=ONBOARDING_STARTED_TOPIC,
                payload_json={"event_type": ONBOARDING_STARTED_EVENT, "status": "IN_PROGRESS"},
                published_at=None,
                attempts=0,
                last_error=None,
                correlation_id=correlation_id,
                causation_id=event.id,
                schema_version="1.0",
                metadata_json={},
                created_by="product_onboarding",
            )
        )


class SqlAlchemyOnboardingRuntime:
    """Own the onboarding adapter lifecycle while API receives only the application use case."""

    def __init__(
        self,
        engine: AsyncEngine,
        service: OnboardingService,
    ) -> None:
        self._engine = engine
        self.service = service

    async def close(self) -> None:
        await self._engine.dispose()
