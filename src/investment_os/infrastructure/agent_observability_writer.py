"""Atomic persistence boundary for completed, finite committee observability."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.agent_registry import AgentRoleRegistry
from investment_os.application.analysis_context import AnalysisContext, require_context_evidence
from investment_os.application.committee_runtime import CommitteeSessionResult
from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.infrastructure.persistence.agent_observability import (
    agent_opinion_record_from_result,
    agent_run_record_from_result,
    committee_message_records_from_result,
    committee_session_record_from_result,
    conflict_records_from_result,
)
from investment_os.infrastructure.persistence.models import (
    AgentOpinionRecord,
    AgentRunRecord,
    CommitteeMessageRecord,
    ConflictRecord,
)
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork


@dataclass(frozen=True, slots=True)
class CommitteeObservabilityWriteResult:
    """Identifiers for the immutable records written in one committed transaction."""

    session_id: UUID
    run_ids: tuple[UUID, ...]
    opinion_ids: tuple[UUID, ...]


class SqlAlchemyCommitteeObservabilityWriter:
    """Append a completed two-round research session without any Decision-side effect."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        now: Callable[[], datetime],
    ) -> None:
        self._session_factory = session_factory
        self._now = now

    async def persist(
        self,
        *,
        result: CommitteeSessionResult,
        context: AnalysisContext,
        registry: AgentRoleRegistry,
        started_at: datetime,
        completed_at: datetime | None = None,
        created_by: str = "committee_runtime",
        correlation_id: UUID | None = None,
    ) -> CommitteeObservabilityWriteResult:
        """Translate runtime-owned requests/results into append-only audit records atomically."""

        if completed_at is None:
            completed_at = self._now()
        if completed_at < started_at:
            raise ApplicationError(
                ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID,
                "committee observability completion cannot precede its start",
            )

        correlation = correlation_id or uuid4()
        session_record = committee_session_record_from_result(
            result=result,
            context=context,
            started_at=started_at,
            completed_at=completed_at,
            created_by=created_by,
            correlation_id=correlation,
        )
        run_records: list[AgentRunRecord] = []
        opinion_records: list[AgentOpinionRecord] = []
        opinion_ids: dict[tuple[int, str], UUID] = {}
        for round_result in result.rounds:
            if not round_result.requests:
                raise ApplicationError(
                    ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID,
                    "committee observability requires each executed gateway request",
                )
            for request, run_result in zip(
                round_result.requests, round_result.results, strict=True
            ):
                if request.input_snapshot_hash != context.input_snapshot_hash:
                    raise ApplicationError(
                        ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID,
                        "committee observability request does not match the frozen AnalysisContext",
                    )
                require_context_evidence(run_result.opinion, context)
                bundle = registry.require(request.role)
                run_record = agent_run_record_from_result(
                    request=request,
                    prompt_bundle=bundle,
                    result=run_result,
                    started_at=started_at,
                    ended_at=completed_at,
                    created_by=created_by,
                    correlation_id=correlation,
                )
                opinion_record = agent_opinion_record_from_result(
                    agent_run_id=run_record.id,
                    result=run_result,
                    created_by=created_by,
                    correlation_id=correlation,
                )
                key = (round_result.plan.number, run_result.opinion.role.value)
                opinion_ids[key] = opinion_record.id
                run_records.append(run_record)
                opinion_records.append(opinion_record)

        messages: tuple[CommitteeMessageRecord, ...] = committee_message_records_from_result(
            session_id=session_record.id,
            result=result,
            opinion_ids=opinion_ids,
            created_by=created_by,
            correlation_id=correlation,
        )
        conflicts: tuple[ConflictRecord, ...] = conflict_records_from_result(
            session_id=session_record.id,
            result=result,
            opinion_ids=opinion_ids,
            created_by=created_by,
            correlation_id=correlation,
        )
        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            await uow.agent_observability.append_session(session_record)
            for run_record in run_records:
                await uow.agent_observability.append_run(run_record)
            for opinion_record in opinion_records:
                await uow.agent_observability.append_opinion(opinion_record)
            for message_record in messages:
                await uow.agent_observability.append_message(message_record)
            for conflict_record in conflicts:
                await uow.agent_observability.append_conflict(conflict_record)
            await uow.commit()

        return CommitteeObservabilityWriteResult(
            session_id=session_record.id,
            run_ids=tuple(record.id for record in run_records),
            opinion_ids=tuple(record.id for record in opinion_records),
        )
