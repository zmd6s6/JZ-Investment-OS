"""Read-only reconstruction of an immutable Decision Journal entry."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.infrastructure.persistence.models import (
    DecisionApprovalRecord,
    DecisionExecutionRecord,
    InvestmentDecisionEvidenceRecord,
    InvestmentDecisionRecord,
)


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
