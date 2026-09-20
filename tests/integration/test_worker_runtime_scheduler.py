from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from investment_os.infrastructure.persistence.models import (
    EventLogRecord,
    OutboxEventRecord,
    TaskRunRecord,
)
from investment_os.infrastructure.report_delivery import DAILY_REPORT_CREATED
from investment_os.infrastructure.runtime_scheduler import SCHEDULED_JOB_COMPLETED
from investment_os.infrastructure.settings import Settings
from investment_os.worker.main import WorkerRuntime


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_runtime_dispatches_explicit_closed_session_once(
    database_engine: AsyncEngine, migrated_database_url: str, tmp_path: Path
) -> None:
    runtime = WorkerRuntime.from_settings(
        Settings(
            database_url=migrated_database_url,
            worker_ready_file=tmp_path / "worker-ready",
            worker_schedule_calendar_path=Path("tests/fixtures/synthetic-runtime-calendar.json"),
        )
    )
    try:
        now = datetime(2027, 1, 1, tzinfo=UTC)
        assert await runtime.run_once(now=now) is True
        assert await runtime.run_once(now=now) is True
    finally:
        await runtime.close()

    async with _factory(database_engine)() as session:
        task_runs = (
            await session.scalars(select(TaskRunRecord).order_by(TaskRunRecord.task_name))
        ).all()
        daily_reports = await session.scalar(
            select(func.count())
            .select_from(EventLogRecord)
            .where(EventLogRecord.event_type == DAILY_REPORT_CREATED)
        )
        scheduled_events = await session.scalar(
            select(func.count())
            .select_from(EventLogRecord)
            .where(EventLogRecord.event_type == SCHEDULED_JOB_COMPLETED)
        )
        outbox_count = await session.scalar(select(func.count()).select_from(OutboxEventRecord))

    assert [run.task_name for run in task_runs] == ["daily", "monthly", "quarterly", "weekly"]
    assert all(run.status == "SUCCEEDED" and run.attempt == 1 for run in task_runs)
    assert daily_reports == 1
    assert scheduled_events == 3
    assert outbox_count == 4
