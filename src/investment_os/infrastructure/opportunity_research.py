"""Append-only candidate authorization intent; it never dispatches work itself."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.opportunities import OpportunityError
from investment_os.application.opportunity_research import CandidateResearchStart
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.infrastructure.persistence.locks import advisory_lock_key
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    EventLogRecord,
    OutboxEventRecord,
)

_KIND = "opportunity_candidate_research"


class SqlCandidateResearchStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self._sessions = sessions

    @staticmethod
    def _read(record: EventLogRecord) -> CandidateResearchStart:
        try:
            raw = record.payload_json["command"]
            command = CandidateResearchStart.model_validate(raw)
            if (
                fingerprint(raw) != record.payload_json["command_hash"]
                or command.analysis.request_id != record.aggregate_id
            ):
                raise ValueError("invalid intent")
            return command
        except (ValueError, KeyError, TypeError):
            raise OpportunityError("CANDIDATE_INTENT_INVALID") from None

    async def record(self, command: CandidateResearchStart) -> CandidateResearchStart:
        identifier = command.analysis.request_id
        raw = command.model_dump(mode="json")
        digest = fingerprint(raw)
        async with self._sessions() as session, session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": advisory_lock_key(_KIND, str(identifier))},
            )
            previous = await session.scalar(
                select(EventLogRecord).where(
                    EventLogRecord.aggregate_type == _KIND,
                    EventLogRecord.aggregate_id == identifier,
                )
            )
            if previous is not None:
                existing = self._read(previous)
                if existing != command:
                    raise OpportunityError("REQUEST_CONTENT_CONFLICT")
                return existing
            event = EventLogRecord(
                id=uuid4(),
                event_type="opportunity.research.explicit_request",
                aggregate_type=_KIND,
                aggregate_id=identifier,
                occurred_at=datetime.now(UTC),
                correlation_id=identifier,
                created_by="opportunity_research",
                payload_json={"command": raw, "command_hash": digest},
            )
            session.add(event)
            await session.flush()
            session.add(
                AuditLogRecord(
                    actor_type="HUMAN",
                    actor_id="local-owner",
                    operation="OPPORTUNITY_RESEARCH_EXPLICIT_REQUEST",
                    entity_type=_KIND,
                    entity_id=identifier,
                    before_hash=None,
                    after_hash=digest,
                    ip_or_runtime_ref="opportunity_research",
                    occurred_at=datetime.now(UTC),
                    correlation_id=identifier,
                    created_by="opportunity_research",
                )
            )
            session.add(
                OutboxEventRecord(
                    event_id=event.id,
                    topic="opportunity.research.intent.recorded",
                    payload_json={"request_id": str(identifier), "command_hash": digest},
                    correlation_id=identifier,
                    created_by="opportunity_research",
                )
            )
        return command

    async def list_for(self, funnel_run_id: UUID) -> tuple[CandidateResearchStart, ...]:
        async with self._sessions() as session:
            records = (
                await session.scalars(
                    select(EventLogRecord)
                    .where(
                        EventLogRecord.aggregate_type == _KIND,
                        EventLogRecord.payload_json["command"]["funnel_run_id"].astext
                        == str(funnel_run_id),
                    )
                    .order_by(EventLogRecord.occurred_at.desc(), EventLogRecord.id.desc())
                    .limit(100)
                )
            ).all()
            return tuple(self._read(record) for record in records)
