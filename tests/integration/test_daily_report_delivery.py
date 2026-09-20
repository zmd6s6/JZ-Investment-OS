from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from investment_os.application.reports import (
    DailyOperatingReport,
    DailyReportSection,
    DailyReportSectionKind,
    ReportStatement,
    ReportStatementKind,
)
from investment_os.infrastructure.persistence.jobs import ReliableJobExecutor
from investment_os.infrastructure.persistence.models import EventLogRecord, OutboxEventRecord
from investment_os.infrastructure.report_delivery import (
    DAILY_REPORT_CREATED,
    DAILY_REPORT_TOPIC,
    daily_report_handler,
)

NOW = datetime(2026, 9, 20, 20, 0, tzinfo=UTC)
HASH = "b" * 64


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _report() -> DailyOperatingReport:
    return DailyOperatingReport(
        as_of=NOW,
        sections=tuple(
            DailyReportSection(
                kind=kind,
                statements=(
                    ReportStatement(
                        kind=ReportStatementKind.ASSUMPTION,
                        content="Synthetic report fixture; no action was submitted.",
                    ),
                )
                if kind is DailyReportSectionKind.ACTION_REQUIRED
                else (),
            )
            for kind in DailyReportSectionKind
        ),
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_daily_report_job_creates_one_immutable_event_and_outbox_record(
    database_engine: AsyncEngine,
) -> None:
    report = _report()
    correlation_id = uuid4()
    executor = ReliableJobExecutor(_factory(database_engine), now=lambda: NOW)
    handler = daily_report_handler(report, correlation_id)

    first = await executor.execute(
        task_name="daily-report",
        scheduled_for=NOW,
        idempotency_key="daily-report:2026-09-20",
        input_hash=HASH,
        handler=handler,
        correlation_id=correlation_id,
    )
    repeated = await executor.execute(
        task_name="daily-report",
        scheduled_for=NOW,
        idempotency_key="daily-report:2026-09-20",
        input_hash=HASH,
        handler=handler,
        correlation_id=correlation_id,
    )

    async with _factory(database_engine)() as session:
        event = (
            await session.scalars(
                select(EventLogRecord).where(EventLogRecord.aggregate_id == report.id)
            )
        ).one()
        outbox = (
            await session.scalars(
                select(OutboxEventRecord).where(OutboxEventRecord.event_id == event.id)
            )
        ).one()
        event_count = await session.scalar(select(func.count()).select_from(EventLogRecord))
        outbox_count = await session.scalar(select(func.count()).select_from(OutboxEventRecord))

    assert first.reused is False
    assert repeated.reused is True
    assert repeated.task_run_id == first.task_run_id
    assert event_count == 1
    assert outbox_count == 1
    assert event.event_type == DAILY_REPORT_CREATED
    assert event.payload_json["content_hash"] == report.content_hash()
    assert event.payload_json["simulation_only"] is True
    assert "SIMULATION / NO AUTO TRADE" in event.payload_json["rendered_markdown"]
    assert outbox.topic == DAILY_REPORT_TOPIC
    assert outbox.payload_json["report_id"] == str(report.id)
    assert outbox.payload_json["content_hash"] == report.content_hash()
