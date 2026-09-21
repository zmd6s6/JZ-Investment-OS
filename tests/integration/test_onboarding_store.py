from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from investment_os.application.onboarding import OnboardingService
from investment_os.infrastructure.onboarding import SqlAlchemyOnboardingStore
from investment_os.infrastructure.persistence.models import EventLogRecord, OutboxEventRecord


async def test_onboarding_state_survives_store_recreation(database_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(database_engine, expire_on_commit=False, class_=AsyncSession)
    first = OnboardingService(SqlAlchemyOnboardingStore(factory))

    assert (await first.current_state()).status == "NOT_STARTED"
    started = await first.start()
    restarted = await OnboardingService(SqlAlchemyOnboardingStore(factory)).current_state()

    assert started.status == "IN_PROGRESS"
    assert started.started_at is not None
    assert restarted == started


async def test_onboarding_start_writes_one_event_and_outbox_message_in_the_same_flow(
    database_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(database_engine, expire_on_commit=False, class_=AsyncSession)
    store = SqlAlchemyOnboardingStore(factory)

    await store.start()
    await store.start()

    async with factory() as session:
        event_count = await session.scalar(select(func.count()).select_from(EventLogRecord))
        outbox_count = await session.scalar(select(func.count()).select_from(OutboxEventRecord))

    assert event_count == 1
    assert outbox_count == 1
