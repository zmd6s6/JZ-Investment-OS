"""Transactional lifecycle and append-only evidence-linked shadow-analysis persistence."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.analysis_runs import (
    AnalysisCancelled,
    AnalysisFrozenInput,
    AnalysisLeaseLost,
    AnalysisQueuedInput,
    AnalysisRunView,
    AnalysisStep,
    ShadowDecision,
)
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.domain.analysis_run import (
    TERMINAL_ANALYSIS,
    AnalysisStatus,
    require_analysis_transition,
)
from investment_os.infrastructure.persistence.analysis_models import (
    AnalysisEvidenceRecord,
    AnalysisInputRecord,
    AnalysisRunRecord,
    AnalysisShadowDecisionRecord,
    AnalysisShadowEvidenceRecord,
    AnalysisStepRecord,
)
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    EventLogRecord,
    EvidenceRecord,
    OutboxEventRecord,
)


def audit(run_id: UUID) -> dict[str, Any]:
    return {
        "created_by": "analysis_runtime",
        "correlation_id": run_id,
        "causation_id": None,
        "schema_version": "1.0",
        "metadata_json": {},
    }


async def emit(
    session: AsyncSession, record: AnalysisRunRecord, kind: str, payload: dict[str, object]
) -> None:
    event = EventLogRecord(
        event_type=f"analysis.{kind}",
        aggregate_type="AnalysisRun",
        aggregate_id=record.id,
        payload_json=payload,
        occurred_at=datetime.now(UTC),
        **audit(record.id),
    )
    session.add(event)
    await session.flush()
    session.add(
        OutboxEventRecord(
            event_id=event.id,
            topic=f"analysis.{kind}",
            payload_json={"event_id": str(event.id), "run_id": str(record.id)},
            published_at=None,
            attempts=0,
            last_error=None,
            **audit(record.id),
        )
    )
    session.add(
        AuditLogRecord(
            actor_type="SYSTEM",
            actor_id="analysis_runtime",
            operation=f"analysis.{kind}",
            entity_type="AnalysisRun",
            entity_id=record.id,
            before_hash=None,
            after_hash=fingerprint(payload),
            ip_or_runtime_ref="worker_or_local_api",
            occurred_at=datetime.now(UTC),
            **audit(record.id),
        )
    )


async def locked(
    session: AsyncSession, run_id: UUID, lease: UUID | None = None
) -> AnalysisRunRecord:
    record = await session.get(AnalysisRunRecord, run_id, with_for_update=True)
    if record is None:
        raise LookupError("ANALYSIS_NOT_FOUND")
    if lease is not None and (record.status != "RUNNING" or record.lease_id != lease):
        raise AnalysisLeaseLost("ANALYSIS_LEASE_LOST")
    return record


async def append_step(
    session: AsyncSession,
    record: AnalysisRunRecord,
    *,
    stage: str,
    status: str,
    payload: dict[str, object],
    reason_code: str | None = None,
) -> None:
    run_id = record.id
    last = await session.scalar(
        select(func.max(AnalysisStepRecord.sequence)).where(AnalysisStepRecord.run_id == run_id)
    )
    row = AnalysisStepRecord(
        run_id=run_id,
        sequence=(last or 0) + 1,
        stage=stage,
        status=status,
        reason_code=reason_code,
        occurred_at=datetime.now(UTC),
        payload_json=payload,
        **audit(run_id),
    )
    session.add(row)
    await emit(
        session,
        record,
        "stage",
        {"stage": stage, "status": status, "sequence": row.sequence},
    )


class SqlAnalysisRuns:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self._sessions = sessions

    async def find_request(self, request_id: UUID) -> AnalysisRunView | None:
        async with self._sessions() as session:
            record = await session.scalar(
                select(AnalysisRunRecord).where(AnalysisRunRecord.request_id == request_id)
            )
            return await self._view(session, record) if record else None

    async def enqueue(self, snapshot: AnalysisQueuedInput) -> AnalysisRunView:
        command = snapshot.command
        request_hash = fingerprint(command.model_dump(mode="json"))
        async with self._sessions() as session, session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"analysis-request-{command.request_id}"},
            )
            existing = await session.scalar(
                select(AnalysisRunRecord).where(AnalysisRunRecord.request_id == command.request_id)
            )
            if existing:
                if existing.request_hash != request_hash:
                    raise ValueError("ANALYSIS_REQUEST_CONFLICT")
                return await self._view(session, existing)
            if command.retry_of:
                prior = await session.get(AnalysisRunRecord, command.retry_of)
                if not prior or AnalysisStatus(prior.status) not in TERMINAL_ANALYSIS:
                    raise ValueError("ANALYSIS_RETRY_REQUIRES_TERMINAL_RUN")
                if (
                    prior.portfolio_id != command.portfolio_id
                    or prior.instrument_id != command.instrument_id
                ):
                    raise ValueError("ANALYSIS_RETRY_TARGET_MISMATCH")
            run_id = uuid4()
            record = AnalysisRunRecord(
                id=run_id,
                request_id=command.request_id,
                portfolio_id=command.portfolio_id,
                instrument_id=command.instrument_id,
                retry_of=command.retry_of,
                status="QUEUED",
                queued_at=snapshot.queued_at,
                lease_id=None,
                cancel_requested=False,
                request_hash=request_hash,
                queued_input_json=snapshot.model_dump(mode="json"),
                policy_version_id=snapshot.valuation.input_snapshot.policy.version_id,
                version=1,
                **audit(run_id),
            )
            session.add(record)
            await session.flush()
            await emit(session, record, "queued", {"request_hash": request_hash})
            return await self._view(session, record)

    async def get(self, run_id: UUID) -> AnalysisRunView:
        async with self._sessions() as session:
            record = await session.get(AnalysisRunRecord, run_id)
            if record is None:
                raise LookupError("ANALYSIS_NOT_FOUND")
            return await self._view(session, record)

    async def list_runs(
        self, *, portfolio_id: UUID | None = None, limit: int = 30
    ) -> tuple[AnalysisRunView, ...]:
        async with self._sessions() as session:
            statement = (
                select(AnalysisRunRecord)
                .order_by(AnalysisRunRecord.queued_at.desc(), AnalysisRunRecord.id)
                .limit(max(1, min(limit, 100)))
            )
            if portfolio_id:
                statement = statement.where(AnalysisRunRecord.portfolio_id == portfolio_id)
            records = (await session.scalars(statement)).all()
            return tuple([await self._view(session, record, details=False) for record in records])

    async def claim_next(self) -> tuple[UUID, UUID, AnalysisQueuedInput] | None:
        async with self._sessions() as session, session.begin():
            record = await session.scalar(
                select(AnalysisRunRecord)
                .where(AnalysisRunRecord.status == "QUEUED")
                .order_by(AnalysisRunRecord.queued_at, AnalysisRunRecord.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if record is None:
                return None
            require_analysis_transition(AnalysisStatus(record.status), AnalysisStatus.RUNNING)
            record.status = "RUNNING"
            record.started_at = datetime.now(UTC)
            record.lease_id = uuid4()
            record.version += 1
            await emit(session, record, "started", {"lease_id": str(record.lease_id)})
            return (
                record.id,
                record.lease_id,
                AnalysisQueuedInput.model_validate(record.queued_input_json),
            )

    async def check_running(self, run_id: UUID, lease: UUID) -> None:
        async with self._sessions() as session:
            record = await session.get(AnalysisRunRecord, run_id)
            if not record or record.status != "RUNNING" or record.lease_id != lease:
                raise AnalysisLeaseLost("ANALYSIS_LEASE_LOST")
            if record.cancel_requested:
                raise AnalysisCancelled("ANALYSIS_CANCEL_REQUESTED")

    async def cancel(self, run_id: UUID) -> AnalysisRunView:
        async with self._sessions() as session, session.begin():
            record = await locked(session, run_id)
            if AnalysisStatus(record.status) in TERMINAL_ANALYSIS or record.cancel_requested:
                return await self._view(session, record)
            record.cancel_requested = True
            record.version += 1
            if record.status == "QUEUED":
                require_analysis_transition(AnalysisStatus.QUEUED, AnalysisStatus.CANCELLED)
                record.status = "CANCELLED"
                record.finished_at = datetime.now(UTC)
            await emit(session, record, "cancel_requested", {"status": record.status})
            return await self._view(session, record)

    async def freeze(self, run_id: UUID, lease: UUID, value: AnalysisFrozenInput) -> None:
        if (
            value.run_id != run_id
            or fingerprint(value.model_dump(mode="json", exclude={"input_hash"}))
            != value.input_hash
        ):
            raise ValueError("ANALYSIS_INPUT_HASH_MISMATCH")
        async with self._sessions() as session, session.begin():
            record = await locked(session, run_id, lease)
            if record.cancel_requested:
                raise AnalysisCancelled("ANALYSIS_CANCEL_REQUESTED")
            if record.input_hash:
                if record.input_hash != value.input_hash:
                    raise ValueError("ANALYSIS_INPUT_ALREADY_FROZEN")
                return
            if value.queued.command.request_id != record.request_id:
                raise ValueError("ANALYSIS_INPUT_REQUEST_MISMATCH")
            record.input_hash = value.input_hash
            record.version += 1
            session.add(
                AnalysisInputRecord(
                    run_id=run_id,
                    as_of=value.as_of,
                    input_hash=value.input_hash,
                    payload_json=value.model_dump(mode="json"),
                    **audit(run_id),
                )
            )
            for item in value.evidence:
                source = await session.get(EvidenceRecord, item.evidence_id)
                if source is None or source.content_hash != item.content_hash:
                    raise ValueError("ANALYSIS_EVIDENCE_HASH_MISMATCH")
                session.add(
                    AnalysisEvidenceRecord(
                        run_id=run_id,
                        evidence_id=item.evidence_id,
                        content_hash=item.content_hash,
                        eligible=item.freshness == "FRESH",
                    )
                )
            await emit(session, record, "inputs_frozen", {"input_hash": value.input_hash})

    async def step(
        self,
        run_id: UUID,
        lease: UUID,
        *,
        stage: str,
        status: str,
        payload: dict[str, object],
        reason_code: str | None = None,
    ) -> None:
        if status not in {"RUNNING", "COMPLETED", "BLOCKED", "FAILED"}:
            raise ValueError("ANALYSIS_STEP_STATUS_INVALID")
        async with self._sessions() as session, session.begin():
            record = await locked(session, run_id, lease)
            await append_step(
                session,
                record,
                stage=stage,
                status=status,
                payload=payload,
                reason_code=reason_code,
            )

    async def finish(
        self,
        run_id: UUID,
        lease: UUID,
        *,
        status: AnalysisStatus,
        error_code: str | None = None,
        result: ShadowDecision | None = None,
    ) -> None:
        if status not in TERMINAL_ANALYSIS:
            raise ValueError("ANALYSIS_TERMINAL_REQUIRED")
        if (status in {AnalysisStatus.SUCCEEDED, AnalysisStatus.DEGRADED}) != (result is not None):
            raise ValueError("ANALYSIS_RESULT_TERMINAL_MISMATCH")
        async with self._sessions() as session, session.begin():
            record = await locked(session, run_id, lease)
            if record.cancel_requested:
                status = AnalysisStatus.CANCELLED
                result = None
            require_analysis_transition(AnalysisStatus(record.status), status)
            if result:
                if (
                    result.policy_version_id != record.policy_version_id
                    or result.input_hash != record.input_hash
                ):
                    raise ValueError("ANALYSIS_RESULT_SNAPSHOT_MISMATCH")
                eligible = set(
                    (
                        await session.scalars(
                            select(AnalysisEvidenceRecord.evidence_id).where(
                                AnalysisEvidenceRecord.run_id == run_id,
                                AnalysisEvidenceRecord.eligible.is_(True),
                            )
                        )
                    ).all()
                )
                cited = {
                    identifier for reason in result.reasons for identifier in reason.evidence_ids
                }
                if not cited or not cited <= eligible:
                    raise ValueError("ANALYSIS_RESULT_EVIDENCE_UNAVAILABLE")
                decision = AnalysisShadowDecisionRecord(
                    run_id=run_id,
                    action=result.action.value,
                    risk_intent=result.risk_intent.value,
                    risk_gate=result.risk_gate,
                    policy_version_id=result.policy_version_id,
                    thesis_version_id=result.thesis_version_id,
                    sizing_run_id=None,
                    input_hash=result.input_hash,
                    content_hash=fingerprint(result.model_dump(mode="json")),
                    payload_json=result.model_dump(mode="json"),
                    execution_allowed=False,
                    auto_trade=False,
                    **audit(run_id),
                )
                session.add(decision)
                await session.flush()
                session.add_all(
                    [
                        AnalysisShadowEvidenceRecord(
                            decision_id=decision.id, run_id=run_id, evidence_id=identifier
                        )
                        for identifier in cited
                    ]
                )
            record.status = status.value
            record.finished_at = datetime.now(UTC)
            record.error_code = error_code
            record.lease_id = None
            record.version += 1
            await emit(
                session,
                record,
                "finished",
                {"status": status.value, "error_code": error_code, "input_hash": record.input_hash},
            )

    async def expire_interrupted(self, *, older_than: datetime) -> int:
        async with self._sessions() as session, session.begin():
            records = (
                await session.scalars(
                    select(AnalysisRunRecord)
                    .where(
                        AnalysisRunRecord.status == "RUNNING",
                        AnalysisRunRecord.started_at < older_than,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for record in records:
                record.status = "FAILED"
                record.finished_at = datetime.now(UTC)
                record.error_code = "ANALYSIS_INTERRUPTED_RETRY_REQUIRED"
                record.lease_id = None
                record.version += 1
                await emit(session, record, "interrupted", {"code": record.error_code})
            return len(records)

    async def _view(
        self, session: AsyncSession, record: AnalysisRunRecord, *, details: bool = True
    ) -> AnalysisRunView:
        steps: tuple[AnalysisStep, ...] = ()
        frozen = None
        result = None
        if details:
            rows = (
                await session.scalars(
                    select(AnalysisStepRecord)
                    .where(AnalysisStepRecord.run_id == record.id)
                    .order_by(AnalysisStepRecord.sequence)
                )
            ).all()
            steps = tuple(
                AnalysisStep(
                    sequence=row.sequence,
                    stage=row.stage,
                    status=row.status,
                    occurred_at=row.occurred_at,
                    reason_code=row.reason_code,
                    payload=row.payload_json,
                )
                for row in rows
            )
            inputs = await session.scalar(
                select(AnalysisInputRecord).where(AnalysisInputRecord.run_id == record.id)
            )
            if inputs:
                frozen = AnalysisFrozenInput.model_validate(inputs.payload_json)
            shadow = await session.scalar(
                select(AnalysisShadowDecisionRecord).where(
                    AnalysisShadowDecisionRecord.run_id == record.id
                )
            )
            if shadow:
                result = ShadowDecision.model_validate(shadow.payload_json)
        return AnalysisRunView(
            run_id=record.id,
            request_id=record.request_id,
            portfolio_id=record.portfolio_id,
            instrument_id=record.instrument_id,
            status=record.status,
            queued_at=record.queued_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            cancel_requested=record.cancel_requested,
            retry_of=record.retry_of,
            error_code=record.error_code,
            request_hash=record.request_hash,
            input_hash=record.input_hash,
            policy_version_id=record.policy_version_id,
            steps=steps,
            frozen_input=frozen,
            shadow_decision=result,
        )
