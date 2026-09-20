from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from investment_os.application.reports import (
    DailyOperatingReport,
    DailyReportSection,
    DailyReportSectionKind,
)
from investment_os.application.schedule import JobCadence, ScheduledJob
from investment_os.infrastructure.daily_report_scheduler import DailyReportScheduler
from investment_os.infrastructure.persistence.jobs import JobExecutionResult
from investment_os.infrastructure.report_delivery import DailyReportEventHandler
from investment_os.infrastructure.scheduler import ScheduledJobDispatcher

NOW = datetime(2026, 9, 20, 20, 0, tzinfo=UTC)


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.result = JobExecutionResult(task_run_id=uuid4(), attempt=1, reused=False)

    async def execute(self, **kwargs: Any) -> JobExecutionResult:
        self.calls.append(kwargs)
        return self.result


def _report(*, as_of: datetime = NOW) -> DailyOperatingReport:
    return DailyOperatingReport(
        as_of=as_of,
        sections=tuple(
            DailyReportSection(kind=kind, statements=()) for kind in DailyReportSectionKind
        ),
    )


def _job(*, cadence: JobCadence = JobCadence.DAILY, as_of: datetime = NOW) -> ScheduledJob:
    return ScheduledJob(name="daily", cadence=cadence, as_of=as_of, scheduled_for=NOW)


@pytest.mark.asyncio
async def test_daily_report_scheduler_binds_hash_and_delivery_handler() -> None:
    executor = FakeExecutor()
    report = _report()
    correlation_id = uuid4()

    result = await DailyReportScheduler(ScheduledJobDispatcher(executor)).dispatch(
        job=_job(), report=report, dry_run=False, correlation_id=correlation_id
    )

    assert result.task_run_id == executor.result.task_run_id
    assert executor.calls[0]["input_hash"] == report.content_hash()
    assert executor.calls[0]["correlation_id"] == correlation_id
    handler = executor.calls[0]["handler"]
    assert isinstance(handler, DailyReportEventHandler)
    assert handler.report == report
    assert handler.correlation_id == correlation_id


@pytest.mark.asyncio
async def test_daily_report_scheduler_rejects_wrong_cadence_without_dispatching() -> None:
    executor = FakeExecutor()

    with pytest.raises(ValueError, match="DAILY"):
        await DailyReportScheduler(ScheduledJobDispatcher(executor)).dispatch(
            job=_job(cadence=JobCadence.WEEKLY), report=_report(), dry_run=False
        )

    assert executor.calls == []


@pytest.mark.asyncio
async def test_daily_report_scheduler_rejects_as_of_drift_without_dispatching() -> None:
    executor = FakeExecutor()

    with pytest.raises(ValueError, match="as_of"):
        await DailyReportScheduler(ScheduledJobDispatcher(executor)).dispatch(
            job=_job(), report=_report(as_of=NOW - timedelta(seconds=1)), dry_run=False
        )

    assert executor.calls == []
