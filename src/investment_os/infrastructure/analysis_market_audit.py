"""Typed append-only market attempt events, independent of final report persistence."""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.analysis_market import MarketAttemptEvent
from investment_os.application.analysis_models import digest
from investment_os.application.analysis_progress import AnalysisCancelled
from investment_os.infrastructure.persistence.models import (
    AnalysisJobRecord,
    AnalysisRunRecord,
    AuditLogRecord,
    EventLogRecord,
    OutboxEventRecord,
)

EVENT_TYPE = "ANALYSIS_MARKET_ATTEMPT"


class SqlAnalysisMarketAudit:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @staticmethod
    async def _events(session: AsyncSession, run_id: UUID) -> tuple[MarketAttemptEvent, ...]:
        rows = await session.scalars(
            select(EventLogRecord)
            .where(
                EventLogRecord.aggregate_type == "analysis_run",
                EventLogRecord.aggregate_id == run_id,
                EventLogRecord.event_type == EVENT_TYPE,
            )
            .order_by(EventLogRecord.occurred_at, EventLogRecord.id)
        )
        return tuple(MarketAttemptEvent.model_validate(row.payload_json) for row in rows)

    async def events(self, run_id: UUID) -> tuple[MarketAttemptEvent, ...]:
        async with self._sessions() as session:
            return await self._events(session, run_id)

    async def append(
        self,
        run_id: UUID,
        event: MarketAttemptEvent,
        *,
        worker_token: UUID | None = None,
    ) -> None:
        async with self._sessions() as session, session.begin():
            run = await session.scalar(
                select(AnalysisRunRecord).where(AnalysisRunRecord.id == run_id).with_for_update()
            )
            job = await session.get(AnalysisJobRecord, run_id)
            if (
                run is None
                or run.status != "RUNNING"
                or (job is not None and (worker_token is None or job.worker_token != worker_token))
                or (
                    job is not None
                    and job.cancel_requested_at
                    and event.attempt.status == "STARTED"
                )
            ):
                raise AnalysisCancelled()
            plan = run.payload_json.get("input_snapshot", {}).get("market_plan") or {}
            profiles = plan.get("profiles", [])
            attempt = event.attempt
            if (
                attempt.rank < 0
                or attempt.rank >= len(profiles)
                or str(attempt.profile_id) != profiles[attempt.rank]["profile_id"]
                or attempt.name != profiles[attempt.rank]["name"]
                or attempt.provider_type != profiles[attempt.rank]["provider_type"]
                or event.occurred_at.tzinfo is None
            ):
                raise ValueError("market event does not match frozen plan")
            previous = [
                e for e in await self._events(session, run_id) if e.attempt_id == event.attempt_id
            ]
            if event in previous:
                return
            if previous:
                started = previous[0].attempt
                if (
                    len(previous) != 1
                    or started.status != "STARTED"
                    or attempt.status in ("STARTED", "CONFIGURATION_CHANGED", "CREDENTIAL_MISSING")
                    or event.occurred_at < previous[0].occurred_at
                    or (started.profile_id, started.rank, started.queries)
                    != (attempt.profile_id, attempt.rank, attempt.queries)
                ):
                    raise ValueError("invalid market event transition")
            elif attempt.status not in ("STARTED", "CONFIGURATION_CHANGED", "CREDENTIAL_MISSING"):
                raise ValueError("market result requires committed start")
            payload = event.model_dump(mode="json")
            content_hash = digest(payload)
            identity = uuid4()
            session.add(
                EventLogRecord(
                    id=identity,
                    event_type=EVENT_TYPE,
                    aggregate_type="analysis_run",
                    aggregate_id=run_id,
                    payload_json=payload,
                    occurred_at=event.occurred_at,
                    correlation_id=run_id,
                    schema_version=event.schema_version,
                    metadata_json={"content_hash": content_hash},
                    created_by="analysis_runtime",
                )
            )
            # Ordinary audit/outbox carry identifiers and hash, not quotations or queries.
            metadata = {
                "run_id": str(run_id),
                "attempt_id": str(event.attempt_id),
                "profile_id": str(attempt.profile_id),
                "status": attempt.status,
                "content_hash": content_hash,
            }
            session.add(
                AuditLogRecord(
                    actor_type="SYSTEM",
                    actor_id="analysis_runtime",
                    operation=EVENT_TYPE,
                    entity_type="analysis_run",
                    entity_id=run_id,
                    before_hash=None,
                    after_hash=content_hash,
                    ip_or_runtime_ref="analysis_runtime",
                    occurred_at=event.occurred_at,
                    correlation_id=run_id,
                    created_by="analysis_runtime",
                    metadata_json=metadata,
                )
            )
            session.add(
                OutboxEventRecord(
                    event_id=identity,
                    topic="analysis.market",
                    payload_json=metadata,
                    created_by="analysis_runtime",
                    correlation_id=run_id,
                )
            )
