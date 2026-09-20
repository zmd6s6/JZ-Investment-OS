"""Read-only reconstruction of an immutable Decision Journal entry."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.domain.approval import DecisionApproval
from investment_os.domain.decision import DecisionClaim, DecisionPosition, InvestmentDecision
from investment_os.domain.execution import DecisionExecution
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.persistence.models import (
    DecisionApprovalRecord,
    DecisionExecutionRecord,
    InvestmentDecisionEvidenceRecord,
    InvestmentDecisionRecord,
)
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork


@dataclass(frozen=True, slots=True)
class DecisionApprovalRead:
    """One attributed, immutable approval action in a journal response."""

    id: UUID
    actor_id: str
    action: str
    comment: str | None
    expires_at: datetime | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class DecisionExecutionRead:
    """One immutable paper/manual execution receipt in a journal response."""

    id: UUID
    approval_id: UUID
    execution_mode: str
    status: str
    requested_quantity: Decimal
    filled_quantity: Decimal
    avg_price: Decimal | None
    external_refs: tuple[str, ...]
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class DecisionJournalRead:
    """Detached audit snapshot that is safe to present from the API layer."""

    decision_id: UUID
    instrument_id: UUID
    portfolio_id: UUID
    committee_session_id: UUID | None
    thesis_version_id: UUID | None
    policy_version_id: UUID
    strategy_version_id: UUID
    risk_assessment_id: UUID | None
    position_sizing_run_id: UUID | None
    action: str
    confidence: Decimal
    risk_intent: str
    core_action: str
    tactical_action: str
    state: str
    reasons: object
    risks: object
    watch_conditions: object
    invalidation_conditions: object
    position_before: object
    position_after_proposed: object
    unknowns: object
    dissent: object
    next_review_at: datetime
    input_snapshot_hash: str
    prompt_bundle_version: str
    formula_version: str
    content_hash: str
    version: int
    evidence_ids: tuple[UUID, ...]
    approvals: tuple[DecisionApprovalRead, ...]
    executions: tuple[DecisionExecutionRead, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DecisionWriteResult:
    """Identity of an immutable Decision snapshot persisted by the journal writer."""

    decision_id: UUID
    content_hash: str


class SqlAlchemyDecisionJournalReader:
    """Reconstruct one Decision and its immutable audit links without mutating state."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, decision_id: UUID) -> DecisionJournalRead | None:
        async with self._session_factory() as session:
            decision = await session.get(InvestmentDecisionRecord, decision_id)
            if decision is None:
                return None
            evidence_ids = tuple(
                (
                    await session.scalars(
                        select(InvestmentDecisionEvidenceRecord.evidence_id)
                        .where(
                            InvestmentDecisionEvidenceRecord.investment_decision_id == decision.id
                        )
                        .order_by(InvestmentDecisionEvidenceRecord.evidence_id)
                    )
                ).all()
            )
            approvals = tuple(
                DecisionApprovalRead(
                    id=record.id,
                    actor_id=record.actor_id,
                    action=record.action,
                    comment=record.comment,
                    expires_at=record.expires_at,
                    occurred_at=record.created_at,
                )
                for record in (
                    await session.scalars(
                        select(DecisionApprovalRecord)
                        .where(DecisionApprovalRecord.decision_id == decision.id)
                        .order_by(DecisionApprovalRecord.created_at, DecisionApprovalRecord.id)
                    )
                ).all()
            )
            executions = tuple(
                DecisionExecutionRead(
                    id=record.id,
                    approval_id=record.approval_id,
                    execution_mode=record.execution_mode,
                    status=record.status,
                    requested_quantity=record.requested_quantity,
                    filled_quantity=record.filled_quantity,
                    avg_price=record.avg_price,
                    external_refs=tuple(record.external_refs_json),
                    occurred_at=record.created_at,
                )
                for record in (
                    await session.scalars(
                        select(DecisionExecutionRecord)
                        .where(DecisionExecutionRecord.decision_id == decision.id)
                        .order_by(DecisionExecutionRecord.created_at, DecisionExecutionRecord.id)
                    )
                ).all()
            )
            return DecisionJournalRead(
                decision_id=decision.id,
                instrument_id=decision.instrument_id,
                portfolio_id=decision.portfolio_id,
                committee_session_id=decision.committee_session_id,
                thesis_version_id=decision.thesis_version_id,
                policy_version_id=decision.policy_version_id,
                strategy_version_id=decision.strategy_version_id,
                risk_assessment_id=decision.risk_assessment_id,
                position_sizing_run_id=decision.position_sizing_run_id,
                action=decision.action,
                confidence=decision.confidence,
                risk_intent=decision.risk_intent,
                core_action=decision.core_action,
                tactical_action=decision.tactical_action,
                state=decision.state,
                reasons=decision.reasons_json,
                risks=decision.risks_json,
                watch_conditions=decision.watch_conditions_json,
                invalidation_conditions=decision.invalidation_conditions_json,
                position_before=decision.position_before_json,
                position_after_proposed=decision.position_after_proposed_json,
                unknowns=decision.unknowns_json,
                dissent=decision.dissent_json,
                next_review_at=decision.next_review_at,
                input_snapshot_hash=decision.input_snapshot_hash,
                prompt_bundle_version=decision.prompt_bundle_version,
                formula_version=decision.formula_version,
                content_hash=decision.content_hash,
                version=decision.version,
                evidence_ids=evidence_ids,
                approvals=approvals,
                executions=executions,
                created_at=decision.created_at,
            )


class SqlAlchemyDecisionJournalWriter:
    """Persist domain-validated Decision, approval, and non-live execution history."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def append_decision(
        self,
        decision: InvestmentDecision,
        *,
        recorded_at: datetime,
        created_by: str = "decision_journal_writer",
        correlation_id: UUID | None = None,
    ) -> DecisionWriteResult:
        """Append a Decision only when its exact Evidence snapshot was available then."""

        occurrence = UtcTimestamp(recorded_at).value
        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            available_ids = await uow.evidence.available_ids(
                decision.evidence_ids,
                instrument_id=decision.instrument_id,
                as_of=occurrence,
            )
            missing_ids = tuple(sorted(set(decision.evidence_ids) - available_ids, key=str))
            if missing_ids:
                raise ApplicationError(
                    ApplicationErrorCode.EVIDENCE_REFERENCE_UNAVAILABLE,
                    "Decision references Evidence unavailable for its recorded business time",
                    details={"evidence_ids": [str(evidence_id) for evidence_id in missing_ids]},
                )
            record = InvestmentDecisionRecord(
                id=decision.id,
                instrument_id=decision.instrument_id,
                portfolio_id=decision.portfolio_id,
                committee_session_id=decision.committee_session_id,
                thesis_version_id=decision.thesis_version_id,
                policy_version_id=decision.policy_version_id,
                strategy_version_id=decision.strategy_version_id,
                risk_assessment_id=decision.risk_assessment_id,
                position_sizing_run_id=decision.position_sizing_run_id,
                action=decision.action.value,
                confidence=decision.confidence.value,
                risk_intent=decision.risk_intent.value,
                core_action=decision.core_action.value,
                tactical_action=decision.tactical_action.value,
                state=decision.state.value,
                reasons_json=_claims_payload(decision.reasons),
                risks_json=_claims_payload(decision.risks),
                watch_conditions_json=list(decision.watch_conditions),
                invalidation_conditions_json=list(decision.invalidation_conditions),
                next_review_at=decision.next_review_at.value,
                input_snapshot_hash=decision.input_snapshot_hash,
                position_before_json=_position_payload(decision.position_before),
                position_after_proposed_json=_position_payload(decision.position_after_proposed),
                unknowns_json=list(decision.unknowns),
                dissent_json=list(decision.dissent),
                prompt_bundle_version=decision.prompt_bundle_version,
                formula_version=decision.formula_version,
                content_hash=decision.content_hash,
                version=decision.version,
                created_at=occurrence,
                created_by=created_by,
                correlation_id=correlation_id or uuid4(),
                causation_id=None,
                metadata_json={},
            )
            await uow.decisions.append(record)
            await uow.decisions.link_evidence(record.id, decision.evidence_ids)
            await uow.commit()
        return DecisionWriteResult(decision_id=decision.id, content_hash=decision.content_hash)

    async def append_approval(
        self,
        approval: DecisionApproval,
        *,
        created_by: str = "decision_journal_writer",
        correlation_id: UUID | None = None,
    ) -> None:
        """Append a named human action only against an existing Decision."""

        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            if await uow.decisions.get(approval.decision_id) is None:
                raise LookupError("Decision does not exist")
            await uow.decision_approvals.append(
                DecisionApprovalRecord(
                    id=approval.id,
                    decision_id=approval.decision_id,
                    actor_id=approval.actor_id,
                    action=approval.action.value,
                    comment=approval.comment,
                    expires_at=approval.expires_at.value if approval.expires_at else None,
                    created_at=approval.occurred_at.value,
                    created_by=created_by,
                    correlation_id=correlation_id or uuid4(),
                    causation_id=None,
                    metadata_json={},
                )
            )
            await uow.commit()

    async def append_execution(
        self,
        execution: DecisionExecution,
        *,
        created_by: str = "decision_journal_writer",
        correlation_id: UUID | None = None,
    ) -> None:
        """Append a paper/manual receipt only when its approval is already immutable history."""

        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            approval = await uow.session.get(DecisionApprovalRecord, execution.approval_id)
            if (
                approval is None
                or approval.decision_id != execution.decision_id
                or approval.actor_id != execution.approval.actor_id
                or approval.action != execution.approval.action.value
                or approval.expires_at
                != (execution.approval.expires_at.value if execution.approval.expires_at else None)
            ):
                raise LookupError("execution approval is not immutable Decision history")
            await uow.decision_executions.append(
                DecisionExecutionRecord(
                    id=execution.id,
                    decision_id=execution.decision_id,
                    approval_id=execution.approval_id,
                    execution_mode=execution.mode.value,
                    status=execution.status.value,
                    requested_quantity=execution.requested_quantity.value,
                    filled_quantity=execution.filled_quantity.value,
                    avg_price=execution.average_price,
                    external_refs_json=list(execution.external_references),
                    created_at=execution.recorded_at.value,
                    created_by=created_by,
                    correlation_id=correlation_id or uuid4(),
                    causation_id=None,
                    metadata_json={},
                )
            )
            await uow.commit()


def _claims_payload(claims: tuple[DecisionClaim, ...]) -> list[dict[str, object]]:
    return [
        {
            "text": claim.text,
            "evidence_ids": [str(evidence_id) for evidence_id in claim.evidence_ids],
        }
        for claim in claims
    ]


def _position_payload(position: DecisionPosition) -> dict[str, str]:
    return {
        "total": str(position.total.value),
        "core": str(position.core.value),
        "tactical": str(position.tactical.value),
    }
