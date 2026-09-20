"""Bridge explicit schedule plans to the durable, advisory-locked job executor."""

from dataclasses import dataclass
from datetime import datetime
from re import fullmatch
from typing import Protocol
from uuid import UUID

from investment_os.application.schedule import ScheduledJob
from investment_os.infrastructure.persistence.jobs import JobExecutionResult, JobHandler


class ReliableExecutionPort(Protocol):
    async def execute(
        self,
        *,
        task_name: str,
        scheduled_for: datetime,
        idempotency_key: str,
        input_hash: str,
        handler: JobHandler,
        correlation_id: UUID | None = None,
    ) -> JobExecutionResult: ...


@dataclass(frozen=True, slots=True)
class ScheduledJobDispatch:
    """Visible outcome for a scheduled invocation or a non-mutating dry-run."""

    job: ScheduledJob
    dry_run: bool
    task_run_id: UUID | None
    attempt: int | None
    reused: bool


class ScheduledJobDispatcher:
    """Preserve explicit as-of/idempotency semantics when invoking durable job infrastructure."""

    def __init__(self, executor: ReliableExecutionPort) -> None:
        self._executor = executor

    async def dispatch(
        self,
        *,
        job: ScheduledJob,
        input_hash: str,
        handler: JobHandler,
        dry_run: bool,
        correlation_id: UUID | None = None,
    ) -> ScheduledJobDispatch:
        if fullmatch(r"[0-9a-f]{64}", input_hash) is None:
            raise ValueError("scheduler input_hash must be a lowercase SHA-256 hex digest")
        if dry_run:
            return ScheduledJobDispatch(
                job=job, dry_run=True, task_run_id=None, attempt=None, reused=False
            )
        result = await self._executor.execute(
            task_name=job.name,
            scheduled_for=job.scheduled_for,
            idempotency_key=job.idempotency_key,
            input_hash=input_hash,
            handler=handler,
            correlation_id=correlation_id,
        )
        return ScheduledJobDispatch(
            job=job,
            dry_run=False,
            task_run_id=result.task_run_id,
            attempt=result.attempt,
            reused=result.reused,
        )
