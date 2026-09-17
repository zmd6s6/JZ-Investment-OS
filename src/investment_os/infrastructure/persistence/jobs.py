"""Idempotent, advisory-locked job execution with durable failure records."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.infrastructure.persistence.locks import try_transaction_advisory_lock
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork

JobHandler = Callable[[SqlAlchemyUnitOfWork], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class JobExecutionResult:
    task_run_id: UUID
    attempt: int
    reused: bool


class ReliableJobExecutor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._now = now or (lambda: datetime.now(UTC))

    def _uow(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self._session_factory)

    async def execute(
        self,
        *,
        task_name: str,
        scheduled_for: datetime,
        idempotency_key: str,
        input_hash: str,
        handler: JobHandler,
        correlation_id: UUID | None = None,
    ) -> JobExecutionResult:
        if scheduled_for.utcoffset() is None:
            raise ValueError("scheduled_for must be timezone-aware")
        run_correlation_id = correlation_id or uuid4()
        try:
            async with self._uow() as uow:
                locked = await try_transaction_advisory_lock(
                    uow.session, namespace="task_run", logical_key=idempotency_key
                )
                if not locked:
                    raise ApplicationError(
                        ApplicationErrorCode.JOB_ALREADY_RUNNING,
                        "logical job is already running",
                        details={"idempotency_key": idempotency_key},
                    )

                existing = await uow.task_runs.get_by_idempotency_key(idempotency_key)
                if existing is not None and existing.input_hash != input_hash:
                    raise ApplicationError(
                        ApplicationErrorCode.IDEMPOTENCY_KEY_CONFLICT,
                        "idempotency key was already used with different input",
                        details={"idempotency_key": idempotency_key},
                    )
                if existing is not None and existing.status == "SUCCEEDED":
                    return JobExecutionResult(existing.id, existing.attempt, reused=True)

                task_run = await uow.task_runs.start_or_retry(
                    task_name=task_name,
                    scheduled_for=scheduled_for,
                    idempotency_key=idempotency_key,
                    input_hash=input_hash,
                    started_at=self._now(),
                    correlation_id=run_correlation_id,
                )
                await handler(uow)
                await uow.task_runs.succeed(task_run, finished_at=self._now())
                result = JobExecutionResult(task_run.id, task_run.attempt, reused=False)
                await uow.commit()
                return result
        except ApplicationError:
            raise
        except Exception as exc:
            await self._record_failure(
                task_name=task_name,
                scheduled_for=scheduled_for,
                idempotency_key=idempotency_key,
                input_hash=input_hash,
                correlation_id=run_correlation_id,
                error_type=type(exc).__name__,
            )
            raise

    async def _record_failure(
        self,
        *,
        task_name: str,
        scheduled_for: datetime,
        idempotency_key: str,
        input_hash: str,
        correlation_id: UUID,
        error_type: str,
    ) -> None:
        async with self._uow() as uow:
            locked = await try_transaction_advisory_lock(
                uow.session, namespace="task_run", logical_key=idempotency_key
            )
            if not locked:
                return
            task_run = await uow.task_runs.start_or_retry(
                task_name=task_name,
                scheduled_for=scheduled_for,
                idempotency_key=idempotency_key,
                input_hash=input_hash,
                started_at=self._now(),
                correlation_id=correlation_id,
            )
            await uow.task_runs.fail(
                task_run,
                finished_at=self._now(),
                error_code="JOB_HANDLER_FAILED",
                error_type=error_type,
            )
            await uow.commit()
