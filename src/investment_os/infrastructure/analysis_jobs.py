"""PostgreSQL queue: session locks, atomic state/events, no paid-call replay."""

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from investment_os.application.analysis_jobs import (
    AnalysisJobError,
    AnalysisProgressEvent,
    AnalysisWorkItem,
    ExecuteJob,
)
from investment_os.application.analysis_orchestrator import AnalysisRunResult
from investment_os.application.analysis_product import PreparedAnalysis, StartAnalysisInput
from investment_os.application.analysis_progress import AnalysisCancelled, AnalysisStage, StageState
from investment_os.application.analysis_run import AnalysisRunRead
from investment_os.infrastructure.analysis_run_store import _read
from investment_os.infrastructure.persistence.models import (
    AnalysisJobRecord,
    AnalysisProgressRecord,
    AnalysisRunRecord,
)
from investment_os.infrastructure.research_preview import append_event

ACTIVE = ("QUEUED", "RUNNING")
LOCK_NAMESPACE = 62006


class SqlAlchemyAnalysisJobs:
    def __init__(self, engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._engine, self._sessions = engine, sessions

    async def _event(
        self,
        session: AsyncSession,
        run: AnalysisRunRecord,
        stage: AnalysisStage,
        state: StageState,
        *,
        human: bool = False,
    ) -> None:
        now = datetime.now(UTC)
        sequence = (
            await session.scalar(
                select(func.max(AnalysisProgressRecord.sequence)).where(
                    AnalysisProgressRecord.run_id == run.id,
                )
            )
            or 0
        ) + 1
        session.add(
            AnalysisProgressRecord(
                run_id=run.id,
                sequence=sequence,
                stage=stage,
                state=state,
                occurred_at=now,
                created_by="analysis_worker" if not human else "product_ui",
                correlation_id=run.id,
            )
        )
        run.updated_at = now
        append_event(
            session,
            "ANALYSIS_STAGE",
            run.id,
            run.payload_json["input_snapshot"]["input_hash"],
            {"run_id": str(run.id), "sequence": sequence, "stage": stage, "state": state},
            now,
            aggregate="analysis_run",
            topic="analysis.jobs",
            actor_type="HUMAN" if human else "SYSTEM",
            actor_id="local_owner" if human else "analysis_worker",
        )

    async def submit(
        self,
        request_id: UUID,
        request_hash: str,
        prepare: Callable[[], Awaitable[PreparedAnalysis]],
        *,
        retry_of: UUID | None,
    ) -> AnalysisRunRead:
        async with self._sessions() as session, session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": request_id.int % (2**63)}
            )
            existing = await session.get(AnalysisJobRecord, request_id)
            if existing:
                if existing.request_hash != request_hash:
                    raise AnalysisJobError("analysis_job_request_conflict")
                run = await session.get(AnalysisRunRecord, request_id)
                assert run is not None
                return _read(run)
            if await session.get(AnalysisRunRecord, request_id):
                raise AnalysisJobError("analysis_job_request_conflict")
            prepared = await prepare()
            request = replace(prepared.request, budget_task_id=request_id)
            now = datetime.now(UTC)
            run = AnalysisRunRecord(
                id=request_id,
                instrument_id=request.instrument_id,
                portfolio_id=request.portfolio_id,
                source=request.source,
                status="QUEUED",
                as_of=request.as_of,
                policy_version_label=request.policy_version_label,
                payload_json={
                    "stage": "QUEUED",
                    "execution_mode": "BACKGROUND",
                    "retry_of": str(retry_of) if retry_of else None,
                    "input_snapshot": prepared.snapshot,
                },
                created_by="product_ui",
                created_at=now,
                updated_at=now,
            )
            session.add(run)
            await session.flush()
            session.add(
                AnalysisJobRecord(
                    id=request_id,
                    request_hash=request_hash,
                    request_json=AnalysisWorkItem(request=request).model_dump(mode="json"),
                    retry_of=retry_of,
                    created_by="product_ui",
                    correlation_id=request_id,
                )
            )
            await self._event(session, run, "QUEUED", "STARTED", human=True)
            return _read(run)

    async def events(self, run_id: UUID) -> tuple[AnalysisProgressEvent, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(AnalysisProgressRecord)
                .where(
                    AnalysisProgressRecord.run_id == run_id,
                )
                .order_by(AnalysisProgressRecord.sequence)
            )
            return tuple(
                AnalysisProgressEvent(
                    r.id,
                    r.run_id,
                    r.sequence,
                    cast(AnalysisStage, r.stage),
                    cast(StageState, r.state),
                    r.occurred_at,
                )
                for r in rows
            )

    async def cancel(self, run_id: UUID) -> AnalysisRunRead:
        async with self._sessions() as session, session.begin():
            run = (
                await session.scalars(
                    select(AnalysisRunRecord)
                    .where(
                        AnalysisRunRecord.id == run_id,
                    )
                    .with_for_update()
                )
            ).one_or_none()
            job = await session.get(AnalysisJobRecord, run_id)
            if run is None or job is None:
                raise AnalysisJobError("analysis_job_not_found")
            if run.status not in ACTIVE or job.cancel_requested_at is not None:
                return _read(run)
            job.cancel_requested_at = datetime.now(UTC)
            if run.status == "QUEUED":
                run.status = "CANCELLED"
                run.failure_code = "ANALYSIS_CANCELLED"
                run.failure_detail = "已取消排队任务, 未调用模型。"
                job.finished_at = datetime.now(UTC)
                stage, state = "FINISHED", "CANCELLED"
            else:
                stage, state = "CANCEL_REQUESTED", "REQUESTED"
            run.payload_json = {**run.payload_json, "stage": stage}
            await self._event(
                session, run, cast(AnalysisStage, stage), cast(StageState, state), human=True
            )
            return _read(run)

    async def retry_input(self, run_id: UUID) -> StartAnalysisInput:
        async with self._sessions() as session:
            run = await session.get(AnalysisRunRecord, run_id)
            job = await session.get(AnalysisJobRecord, run_id)
            if run is None or job is None:
                raise AnalysisJobError("analysis_job_not_found")
            if run.status not in ("FAILED", "CANCELLED"):
                raise AnalysisJobError("analysis_job_not_retryable")
            evidence = run.payload_json["input_snapshot"]["evidence"]
            return StartAnalysisInput(
                run.instrument_id,
                run.portfolio_id,
                run.source,
                evidence_ids=tuple(UUID(item["evidence_id"]) for item in evidence),
                market_profile_ids=tuple(
                    UUID(p["profile_id"])
                    for p in (run.payload_json["input_snapshot"].get("market_plan") or {}).get(
                        "profiles", []
                    )
                ),
            )

    async def _progress(
        self, run_id: UUID, token: UUID, stage: AnalysisStage, state: StageState
    ) -> None:
        async with self._sessions() as session, session.begin():
            run = (
                await session.scalars(
                    select(AnalysisRunRecord)
                    .where(
                        AnalysisRunRecord.id == run_id,
                    )
                    .with_for_update()
                )
            ).one()
            job = await session.get(AnalysisJobRecord, run_id)
            if (
                not job
                or run.status != "RUNNING"
                or job.worker_token != token
                or job.cancel_requested_at
            ):
                raise AnalysisCancelled()
            run.payload_json = {**run.payload_json, "stage": stage}
            await self._event(session, run, stage, state)

    async def _finish(self, run_id: UUID, token: UUID, result: AnalysisRunResult) -> None:
        async with self._sessions() as session, session.begin():
            run = (
                await session.scalars(
                    select(AnalysisRunRecord)
                    .where(
                        AnalysisRunRecord.id == run_id,
                    )
                    .with_for_update()
                )
            ).one()
            job = await session.get(AnalysisJobRecord, run_id)
            if not job or job.worker_token != token or run.status != "RUNNING":
                return
            cancelled = (
                job.cancel_requested_at is not None or result.failure_code == "ANALYSIS_CANCELLED"
            )
            run.status = "CANCELLED" if cancelled else result.status
            run.failure_code = "ANALYSIS_CANCELLED" if cancelled else result.failure_code
            run.failure_detail = (
                "已在阶段边界停止; 已发出的上游调用可能仍计费。"
                if cancelled
                else result.failure_detail
            )
            run.payload_json = {
                **run.payload_json,
                **(
                    result.payload.to_dict() if result.payload is not None and not cancelled else {}
                ),
                "stage": "FINISHED",
            }
            job.finished_at = datetime.now(UTC)
            state: StageState = (
                "CANCELLED" if cancelled else "COMPLETED" if run.status == "SUCCEEDED" else "FAILED"
            )
            await self._event(session, run, "FINISHED", state)

    async def _consume(
        self, run_id: UUID, execute: ExecuteJob, connection: AsyncConnection
    ) -> bool:
        backend_pid = await connection.scalar(text("SELECT pg_backend_pid()"))
        await connection.commit()
        async with self._sessions() as session, session.begin():
            run = (
                await session.scalars(
                    select(AnalysisRunRecord)
                    .where(
                        AnalysisRunRecord.id == run_id,
                    )
                    .with_for_update()
                )
            ).one()
            job = await session.get(AnalysisJobRecord, run_id)
            if not job or run.status not in ACTIVE:
                return False
            if run.status == "RUNNING":
                # We own the session lock: the previous consumer no longer holds it.
                run.status, run.failure_code = "FAILED", "ANALYSIS_INTERRUPTED"
                run.failure_detail = "工作进程中断, 未自动重放; 核对费用后可明确发起新运行。"
                run.payload_json = {**run.payload_json, "stage": "FINISHED"}
                job.finished_at = datetime.now(UTC)
                await self._event(session, run, "FINISHED", "FAILED")
                return True
            token = uuid4()
            job.worker_token, job.started_at = token, datetime.now(UTC)
            run.status = "RUNNING"
            work_json = dict(job.request_json)
            evidence_snapshot = run.payload_json["input_snapshot"]["evidence"]
            await self._event(session, run, "QUEUED", "COMPLETED")
        try:
            work = AnalysisWorkItem.model_validate(work_json)

            async def progress(stage: AnalysisStage, state: StageState) -> None:
                current_pid = await connection.scalar(text("SELECT pg_backend_pid()"))
                await connection.commit()
                if current_pid != backend_pid:
                    raise AnalysisJobError("analysis_worker_lock_lost")
                await self._progress(run_id, token, stage, state)

            unavailable = any(
                item.get("ingested_freshness_status") == "STALE"
                or (
                    item.get("expires_at") is not None
                    and datetime.fromisoformat(item["expires_at"]) <= datetime.now(UTC)
                )
                for item in evidence_snapshot
            )
            result = (
                AnalysisRunResult(
                    "FAILED",
                    None,
                    "ANALYSIS_EVIDENCE_UNAVAILABLE",
                    "排队期间资料已过期或陈旧, 未调用模型; 请先核对并准备有效资料。",
                )
                if unavailable
                else await execute(replace(work.request, budget_task_id=run_id), progress)
            )
        except AnalysisCancelled:
            result = AnalysisRunResult("FAILED", None, "ANALYSIS_CANCELLED", "已请求停止。")
        except Exception:
            # No untrusted exception text or secrets in the persisted public error.
            result = AnalysisRunResult(
                "FAILED",
                None,
                "ANALYSIS_EXECUTION_FAILED",
                "分析执行异常; 请核对配置、运行记录与费用后再决定是否重试。",
            )
        await self._finish(run_id, token, result)
        return True

    async def work_once(self, execute: ExecuteJob) -> bool:
        async with self._sessions() as session:
            ids = list(
                await session.scalars(
                    select(AnalysisJobRecord.id)
                    .join(
                        AnalysisRunRecord,
                        AnalysisRunRecord.id == AnalysisJobRecord.id,
                    )
                    .where(AnalysisRunRecord.status.in_(ACTIVE))
                    .order_by(
                        AnalysisJobRecord.created_at,
                        AnalysisJobRecord.id,
                    )
                    .limit(20)
                )
            )
        for run_id in ids:
            async with self._engine.connect() as connection:
                if not await self._lock(connection, run_id, acquire=True):
                    continue
                try:
                    return await self._consume(run_id, execute, connection)
                finally:
                    await self._lock(connection, run_id, acquire=False)
        return False

    @staticmethod
    async def _lock(connection: AsyncConnection, run_id: UUID, *, acquire: bool) -> bool:
        function = "pg_try_advisory_lock" if acquire else "pg_advisory_unlock"
        result = await connection.scalar(
            text(f"SELECT {function}(:namespace, :key)"),
            {
                "namespace": LOCK_NAMESPACE,
                "key": run_id.int % (2**31),
            },
        )
        await connection.commit()
        return bool(result)
