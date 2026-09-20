from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from investment_os.application.schedule import JobCadence, ScheduledJob
from investment_os.infrastructure.persistence.jobs import JobExecutionResult
from investment_os.infrastructure.scheduler import ScheduledJobDispatcher


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.result = JobExecutionResult(task_run_id=uuid4(), attempt=1, reused=False)

    async def execute(self, **kwargs: Any) -> JobExecutionResult:
        self.calls.append(kwargs)
        return self.result


async def _noop(_: object) -> None:
    return None


def _job() -> ScheduledJob:
    as_of = datetime(2026, 9, 20, 20, 0, tzinfo=UTC)
    return ScheduledJob(name="daily", cadence=JobCadence.DAILY, as_of=as_of, scheduled_for=as_of)


@pytest.mark.asyncio
async def test_dispatch_maps_explicit_job_to_durable_executor() -> None:
    executor = FakeExecutor()
    dispatcher = ScheduledJobDispatcher(executor)
    correlation_id = uuid4()

    result = await dispatcher.dispatch(
        job=_job(),
        input_hash="a" * 64,
        handler=_noop,
        dry_run=False,
        correlation_id=correlation_id,
    )

    assert result.task_run_id == executor.result.task_run_id
    assert result.attempt == 1
    assert executor.calls == [
        {
            "task_name": "daily",
            "scheduled_for": datetime(2026, 9, 20, 20, 0, tzinfo=UTC),
            "idempotency_key": "daily:2026-09-20T20:00:00+00:00",
            "input_hash": "a" * 64,
            "handler": _noop,
            "correlation_id": correlation_id,
        }
    ]


@pytest.mark.asyncio
async def test_dry_run_is_non_mutating_and_exposes_the_plan() -> None:
    executor = FakeExecutor()
    dispatcher = ScheduledJobDispatcher(executor)

    result = await dispatcher.dispatch(job=_job(), input_hash="b" * 64, handler=_noop, dry_run=True)

    assert result.dry_run is True
    assert result.task_run_id is None
    assert executor.calls == []


@pytest.mark.asyncio
async def test_dispatch_rejects_non_sha256_input_hash() -> None:
    dispatcher = ScheduledJobDispatcher(FakeExecutor())

    with pytest.raises(ValueError, match="SHA-256"):
        await dispatcher.dispatch(job=_job(), input_hash="not-a-hash", handler=_noop, dry_run=False)
