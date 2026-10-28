"""Transactional human review over immutable Decisions and append-only action history."""

import builtins
import json
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.approval_gate import approval_transition_context
from investment_os.application.decision_center import (
    CenterDetail,
    DecisionCard,
    HumanCommand,
    ManualExecutionCommand,
    clean_text,
    command_hash,
)
from investment_os.application.policy_schema import InvestmentPolicySchema
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.domain.approval import DecisionApproval, DecisionApprovalHistory
from investment_os.domain.enums import (
    Action,
    ApprovalAction,
    DecisionState,
    ExecutionMode,
    ExecutionStatus,
)
from investment_os.domain.execution import DecisionExecution
from investment_os.domain.state_machines import transition_decision
from investment_os.domain.values import Quantity, UtcTimestamp
from investment_os.infrastructure.decision_center_models import (
    DecisionCenterActionRecord,
    ManualExecutionDetailRecord,
)
from investment_os.infrastructure.persistence.models import (
    AgentOpinionRecord,
    AgentRunRecord,
    AuditLogRecord,
    CommitteeMessageRecord,
    CommitteeSessionRecord,
    DecisionApprovalRecord,
    DecisionExecutionRecord,
    EventLogRecord,
    EvidenceRecord,
    InstrumentRecord,
    InvestmentDecisionEvidenceRecord,
    InvestmentDecisionRecord,
    InvestmentPolicyRecord,
    InvestmentPolicyVersionRecord,
    InvestmentThesisRecord,
    OutboxEventRecord,
    PortfolioRecord,
    PositionRecord,
    PositionSizingRunRecord,
    RiskAssessmentRecord,
    ThesisVersionRecord,
)


async def ledger_fingerprint(session: AsyncSession, portfolio_id: UUID) -> str:
    """Exact current P5 cash/position identity; never infer holdings from a model opinion."""
    portfolio = await session.get(PortfolioRecord, portfolio_id)
    positions = (
        await session.scalars(
            select(PositionRecord)
            .where(PositionRecord.portfolio_id == portfolio_id)
            .order_by(PositionRecord.id)
        )
    ).all()
    return fingerprint(
        {
            "portfolio_id": str(portfolio_id),
            "cash": str(portfolio.cash_balance) if portfolio else None,
            "positions": [
                {
                    "id": str(p.id),
                    "version": p.version,
                    "core": str(p.core_quantity),
                    "tactical": str(p.tactical_quantity),
                }
                for p in positions
            ],
        }
    )


class SqlDecisionCenter:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        now: Callable[[], datetime] | None = None,
    ):
        self._sessions = sessions
        self._now = now or (lambda: datetime.now(UTC))

    async def list(self, *, portfolio_id: UUID | None = None) -> tuple[DecisionCard, ...]:
        async with self._sessions() as session:
            query = (
                select(InvestmentDecisionRecord)
                .order_by(InvestmentDecisionRecord.created_at.desc(), InvestmentDecisionRecord.id)
                .limit(100)
            )
            if portfolio_id is not None:
                query = query.where(InvestmentDecisionRecord.portfolio_id == portfolio_id)
            decisions = (await session.scalars(query)).all()
            return tuple([(await self._detail(session, d)).decision for d in decisions])

    async def get(self, decision_id: UUID) -> CenterDetail:
        async with self._sessions() as session:
            decision = await session.get(InvestmentDecisionRecord, decision_id)
            if decision is None:
                raise LookupError("DECISION_NOT_FOUND")
            return await self._detail(session, decision)

    async def _detail(self, session: AsyncSession, d: InvestmentDecisionRecord) -> CenterDetail:
        now = self._now()
        actions = (
            await session.scalars(
                select(DecisionCenterActionRecord)
                .where(DecisionCenterActionRecord.decision_id == d.id)
                .order_by(DecisionCenterActionRecord.revision)
            )
        ).all()
        approvals = (
            await session.scalars(
                select(DecisionApprovalRecord)
                .where(DecisionApprovalRecord.decision_id == d.id)
                .order_by(DecisionApprovalRecord.created_at, DecisionApprovalRecord.id)
            )
        ).all()
        executions = (
            await session.scalars(
                select(DecisionExecutionRecord)
                .where(DecisionExecutionRecord.decision_id == d.id)
                .order_by(DecisionExecutionRecord.created_at, DecisionExecutionRecord.id)
            )
        ).all()
        state = actions[-1].resulting_state if actions else d.state
        revision = actions[-1].revision if actions else d.version
        active = _history(approvals).active_approval_at(UtcTimestamp(now)) if approvals else None
        if state in {"APPROVED", "PARTIALLY_EXECUTED"} and active is None:
            state = "EXPIRED"
        blockers, lineage, quantity = await self._lineage(session, d, now)
        if len(actions) != len(approvals) + len(executions):
            blockers.append("LEGACY_ACTION_HISTORY_REQUIRES_REVIEW")
        filled = sum((e.filled_quantity for e in executions), Decimal(0))
        remaining = max(Decimal(0), quantity - filled) if quantity is not None else None
        allowed = []
        if state == "PENDING_APPROVAL":
            allowed.append("REJECT")
            if not blockers:
                allowed.append("APPROVE")
        if state == "APPROVED" and filled == 0:
            allowed.append("REVOKE")
        if state in {"APPROVED", "PARTIALLY_EXECUTED"} and active and not blockers and remaining:
            allowed.append("RECORD_EXECUTION")
        symbol = await session.get(InstrumentRecord, d.instrument_id)
        history: list[dict[str, object]] = []
        for a in actions:
            item: dict[str, object] = {
                "request_id": str(a.id),
                "revision": a.revision,
                "action": a.action,
                "state": a.resulting_state,
                "actor_id": a.actor_id,
                "comment": a.comment,
                "occurred_at": a.occurred_at.isoformat(),
                "approval_id": str(a.approval_id) if a.approval_id else None,
            }
            if a.execution_id:
                execution = next(e for e in executions if e.id == a.execution_id)
                extra = await session.get(ManualExecutionDetailRecord, a.execution_id)
                item["execution"] = {
                    "execution_id": str(execution.id),
                    "approval_id": str(execution.approval_id),
                    "mode": execution.execution_mode,
                    "quantity": str(execution.filled_quantity),
                    "price": str(execution.avg_price),
                    "references": execution.external_refs_json,
                    "status": execution.status,
                    "fees": str(extra.fees) if extra else None,
                    "executed_at": extra.executed_at.isoformat() if extra else None,
                    "note": extra.note if extra else None,
                }
            history.append(item)
        return CenterDetail(
            decision=DecisionCard(
                decision_id=d.id,
                portfolio_id=d.portfolio_id,
                instrument_id=d.instrument_id,
                symbol=symbol.symbol if symbol else str(d.instrument_id),
                action=d.action,
                state=state,
                revision=revision,
                created_at=d.created_at,
                blockers=tuple(blockers),
            ),
            as_of=now,
            journal={
                "original_state": d.state,
                "content_hash": d.content_hash,
                "input_snapshot_hash": d.input_snapshot_hash,
                "reasons": d.reasons_json,
                "risks": d.risks_json,
                "position_before": d.position_before_json,
                "position_after_proposed": d.position_after_proposed_json,
                "core_action": d.core_action,
                "tactical_action": d.tactical_action,
                "unknowns": d.unknowns_json,
                "dissent": d.dissent_json,
                "watch_conditions": d.watch_conditions_json,
                "invalidation_conditions": d.invalidation_conditions_json,
                "prompt_bundle_version": d.prompt_bundle_version,
                "formula_version": d.formula_version,
            },
            lineage=lineage,
            history=tuple(history),
            approval_id=active.id if active else None,
            approval_expires_at=active.expires_at.value if active and active.expires_at else None,
            approved_quantity=quantity,
            filled_quantity=filled,
            remaining_quantity=remaining,
            allowed_actions=tuple(allowed),
        )

    async def _lineage(
        self, session: AsyncSession, d: InvestmentDecisionRecord, now: datetime
    ) -> tuple[builtins.list[str], dict[str, object], Decimal | None]:
        blockers: list[str] = []
        risk = (
            await session.get(RiskAssessmentRecord, d.risk_assessment_id)
            if d.risk_assessment_id
            else None
        )
        sizing = (
            await session.get(PositionSizingRunRecord, d.position_sizing_run_id)
            if d.position_sizing_run_id
            else None
        )
        policy = await session.get(InvestmentPolicyVersionRecord, d.policy_version_id)
        thesis = (
            await session.get(ThesisVersionRecord, d.thesis_version_id)
            if d.thesis_version_id
            else None
        )
        evidence_ids = (
            await session.scalars(
                select(InvestmentDecisionEvidenceRecord.evidence_id).where(
                    InvestmentDecisionEvidenceRecord.investment_decision_id == d.id
                )
            )
        ).all()
        evidence = (
            (
                await session.scalars(
                    select(EvidenceRecord).where(EvidenceRecord.id.in_(evidence_ids))
                )
            ).all()
            if evidence_ids
            else []
        )
        if not evidence or len(evidence) != len(evidence_ids):
            blockers.append("EVIDENCE_MISSING")
        for e in evidence:
            if (
                e.instrument_id not in {None, d.instrument_id}
                or max(e.observed_at, e.effective_at, e.available_at, e.ingested_at) > d.created_at
                or (e.expires_at and now >= e.expires_at)
                or e.freshness_status != "FRESH"
                or e.quality_score <= 0
            ):
                blockers.append("EVIDENCE_STALE_OR_UNAVAILABLE")
        if thesis is None:
            blockers.append("THESIS_MISSING")
        elif d.action in {"BUY", "ADD"} and thesis.thesis_state not in {"VALID", "STRENGTHENING"}:
            blockers.append("THESIS_NOT_VALID_FOR_INCREASE")
        if thesis is not None:
            parent_thesis = await session.get(InvestmentThesisRecord, thesis.thesis_id)
            if parent_thesis is None or parent_thesis.instrument_id != d.instrument_id:
                blockers.append("THESIS_REFERENCE_MISMATCH")
        if d.created_at > now or d.next_review_at <= now:
            blockers.append("DECISION_REVIEW_DUE")
        committee = (
            await session.get(CommitteeSessionRecord, d.committee_session_id)
            if d.committee_session_id
            else None
        )
        if (
            committee is None
            or committee.instrument_id != d.instrument_id
            or committee.status != "COMPLETED"
        ):
            blockers.append("COMMITTEE_MISSING_OR_INCOMPLETE")
        if risk is None or risk.session_id != d.committee_session_id or risk.expires_at <= now:
            blockers.append("RISK_MISSING_OR_EXPIRED")
        elif not risk.hard_flags_json and not risk.soft_flags_json:
            blockers.append("RISK_UNKNOWN")
        elif risk.hard_flags_json and not risk.veto:
            blockers.append("RISK_VETO_INCONSISTENT")
        elif risk.veto and (d.action in {"BUY", "ADD"} or _increases(d)):
            blockers.append("RISK_VETO")
        elif risk.veto and (
            sizing is None or sizing.input_json.get("risk_reduction_exception_recorded") is not True
        ):
            blockers.append("RISK_REDUCTION_EXCEPTION_MISSING")
        if policy is None:
            blockers.append("POLICY_MISSING")
        else:
            try:
                schema = InvestmentPolicySchema.model_validate_json(json.dumps(policy.config_json))
                if (
                    schema.metadata.status.value != "ACTIVE"
                    or not policy.approved_by
                    or not policy.approved_at
                    or policy.approved_at > now
                    or not policy.effective_from
                    or policy.effective_from > now
                ):
                    blockers.append("POLICY_NOT_APPROVED")
                parent = await session.get(InvestmentPolicyRecord, policy.policy_id)
                if (
                    parent is None
                    or parent.current_version_id != policy.id
                    or parent.status != "ACTIVE"
                ):
                    blockers.append("POLICY_CHANGED")
                portfolio = await session.get(PortfolioRecord, d.portfolio_id)
                if (
                    portfolio is None
                    or portfolio.status != "ACTIVE"
                    or portfolio.policy_id != policy.policy_id
                ):
                    blockers.append("PORTFOLIO_POLICY_MISMATCH")
            except (ValidationError, ValueError):
                blockers.append("POLICY_INVALID")
        quantity = None
        if (
            sizing is None
            or sizing.instrument_id != d.instrument_id
            or sizing.portfolio_id != d.portfolio_id
            or sizing.policy_version_id != d.policy_version_id
            or sizing.formula_version != d.formula_version
        ):
            blockers.append("SIZING_MISSING_OR_MISMATCH")
        else:
            try:
                delta = Decimal(str(sizing.output_json["delta_quantity"]))
                quantity = abs(delta)
                request_input = sizing.input_json.get("request")
                if (
                    not isinstance(request_input, dict)
                    or request_input.get("action") != d.action
                    or request_input.get("risk_intent") != d.risk_intent
                ):
                    raise ValueError("sizing action or intent mismatch")
                if (
                    d.action not in {"BUY", "ADD", "REDUCE", "EXIT"}
                    or (d.action in {"BUY", "ADD"} and delta <= 0)
                    or (d.action in {"REDUCE", "EXIT"} and delta >= 0)
                ):
                    raise ValueError("sizing direction mismatch")
                if (
                    not quantity.is_finite()
                    or quantity <= 0
                    or sizing.output_json["input_hash"] != sizing.input_hash
                    or sizing.output_json["formula_version"] != sizing.formula_version
                ):
                    raise ValueError("invalid sizing result")
                if sizing.input_json.get("ledger_hash") != await ledger_fingerprint(
                    session, d.portfolio_id
                ):
                    blockers.append("PORTFOLIO_INPUT_CHANGED")
                if Decimal(str(sizing.input_json["reference_price"])) <= 0:
                    raise ValueError("missing reference price")
            except (KeyError, ValueError, ArithmeticError):
                quantity = None
                blockers.append("SIZING_INPUT_INVALID")
        strategy = (
            await session.execute(
                text("SELECT id, status, approved_by FROM strategy_version WHERE id=:id"),
                {"id": d.strategy_version_id},
            )
        ).first()
        if strategy is None or strategy.status != "ACTIVE" or not strategy.approved_by:
            blockers.append("STRATEGY_NOT_APPROVED")
        messages = (
            await session.scalars(
                select(CommitteeMessageRecord)
                .where(CommitteeMessageRecord.session_id == d.committee_session_id)
                .order_by(CommitteeMessageRecord.round_number, CommitteeMessageRecord.id)
            )
        ).all()
        opinions: builtins.list[dict[str, object]] = []
        valid_roles: set[str] = set()
        for message in messages:
            opinion = (
                await session.get(AgentOpinionRecord, message.opinion_id)
                if message.opinion_id
                else None
            )
            if opinion is None:
                continue
            run = await session.get(AgentRunRecord, opinion.agent_run_id)
            observations: object = opinion.observations_json
            valid_observations = (
                isinstance(observations, list)
                and bool(observations)
                and all(
                    isinstance(fact, dict)
                    and bool(fact.get("evidence_ids"))
                    and set(fact["evidence_ids"])
                    <= {str(identifier) for identifier in evidence_ids}
                    for fact in observations
                )
            )
            if (
                run is not None
                and run.status == "SUCCEEDED"
                and run.agent_role == message.agent_role
                and opinion.instrument_id == d.instrument_id
                and valid_observations
            ):
                valid_roles.add(message.agent_role)
            opinions.append(
                {
                    "role": message.agent_role,
                    "round": message.round_number,
                    "opinion_id": str(opinion.id),
                    "stance": opinion.stance,
                    "confidence": str(opinion.confidence),
                    "observations": opinion.observations_json,
                    "assumptions": opinion.assumptions_json,
                    "unknowns": opinion.unknowns_json,
                    "model": run.model_name if run else None,
                    "prompt_version": run.prompt_version if run else None,
                }
            )
        if (
            not {"MACRO", "INDUSTRY", "FUNDAMENTAL", "MARKET_QUANT", "EVENT", "DEVILS_ADVOCATE"}
            <= valid_roles
        ):
            blockers.append("COMMITTEE_OPINIONS_MISSING_OR_INVALID")
        lineage: dict[str, object] = {
            "opinions": opinions,
            "thesis_version_id": str(d.thesis_version_id) if d.thesis_version_id else None,
            "thesis": {
                "state": thesis.thesis_state,
                "summary": thesis.summary,
                "pillars": thesis.pillars_json,
                "monitoring": thesis.monitoring_conditions_json,
            }
            if thesis
            else None,
            "committee_session_id": str(committee.id) if committee else None,
            "committee_messages": [
                {
                    "round": message.round_number,
                    "role": message.agent_role,
                    "type": message.message_type,
                    "opinion_id": str(message.opinion_id) if message.opinion_id else None,
                    "payload": message.payload_json,
                }
                for message in (
                    await session.scalars(
                        select(CommitteeMessageRecord)
                        .where(CommitteeMessageRecord.session_id == d.committee_session_id)
                        .order_by(CommitteeMessageRecord.round_number, CommitteeMessageRecord.id)
                    )
                ).all()
            ],
            "policy_version_id": str(d.policy_version_id),
            "strategy_version_id": str(d.strategy_version_id),
            "risk_assessment_id": str(d.risk_assessment_id) if d.risk_assessment_id else None,
            "risk_veto": risk.veto if risk else None,
            "risk_codes": risk.veto_codes if risk else [],
            "risk_expires_at": risk.expires_at.isoformat() if risk else None,
            "sizing_run_id": str(sizing.id) if sizing else None,
            "sizing_input": sizing.input_json if sizing else None,
            "sizing_output": sizing.output_json if sizing else None,
            "evidence": [
                {
                    "evidence_id": str(e.id),
                    "source": e.source_name,
                    "locator": e.source_locator,
                    "available_at": e.available_at.isoformat(),
                    "expires_at": e.expires_at.isoformat() if e.expires_at else None,
                    "content_hash": e.content_hash,
                }
                for e in evidence
            ],
        }
        return list(dict.fromkeys(blockers)), lineage, quantity

    async def act(
        self,
        decision_id: UUID,
        action: Literal["APPROVE", "REJECT", "REVOKE", "RECORD_EXECUTION"],
        command: HumanCommand,
    ) -> CenterDetail:
        async with self._sessions() as session, session.begin():
            # Serialize all commands for this immutable snapshot, including idempotent retries.
            d = await session.get(InvestmentDecisionRecord, decision_id, with_for_update=True)
            if d is None:
                raise LookupError("DECISION_NOT_FOUND")
            # Portfolio parent lock also blocks FK insertions of new positions while
            # existing rows are locked below, closing the final ledger-check window.
            await session.get(PortfolioRecord, d.portfolio_id, with_for_update=True)
            await session.scalars(
                select(PositionRecord)
                .where(PositionRecord.portfolio_id == d.portfolio_id)
                .order_by(PositionRecord.id)
                .with_for_update()
            )
            policy = await session.get(InvestmentPolicyVersionRecord, d.policy_version_id)
            if policy is not None:
                await session.get(InvestmentPolicyRecord, policy.policy_id, with_for_update=True)
            receipt = await session.get(DecisionCenterActionRecord, command.request_id)
            digest = command_hash(action, command)
            if receipt is not None:
                if receipt.decision_id != d.id or receipt.command_hash != digest:
                    raise ValueError("IDEMPOTENCY_CONFLICT")
                return await self._detail(session, d)
            detail = await self._detail(session, d)
            if command.expected_revision != detail.decision.revision:
                raise ValueError("DECISION_REVISION_CONFLICT")
            if action not in detail.allowed_actions:
                raise ValueError("DECISION_ACTION_BLOCKED")
            now = self._now()
            actor, comment = clean_text(command.actor_id), clean_text(command.comment)
            approval_id = execution_id = None
            state = detail.decision.state
            if action != "RECORD_EXECUTION":
                ttl = None
                if action == "APPROVE":
                    policy = await session.get(InvestmentPolicyVersionRecord, d.policy_version_id)
                    assert policy is not None
                    config = InvestmentPolicySchema.model_validate_json(
                        json.dumps(policy.config_json)
                    )
                    ttl = UtcTimestamp(now + timedelta(hours=config.execution.approval_ttl_hours))
                approval = DecisionApproval(
                    decision_id=d.id,
                    actor_id=actor,
                    action=ApprovalAction(action),
                    occurred_at=UtcTimestamp(now),
                    expires_at=ttl,
                    comment=comment,
                )
                approval_id = approval.id
                prior = (
                    await session.scalars(
                        select(DecisionApprovalRecord)
                        .where(DecisionApprovalRecord.decision_id == d.id)
                        .order_by(DecisionApprovalRecord.created_at, DecisionApprovalRecord.id)
                    )
                ).all()
                history = DecisionApprovalHistory(
                    d.id, (*(_history(prior).records if prior else ()), approval)
                )
                target = {
                    "APPROVE": DecisionState.APPROVED,
                    "REJECT": DecisionState.REJECTED,
                    "REVOKE": DecisionState.CANCELLED,
                }[action]
                transition_decision(
                    DecisionState(state),
                    target,
                    approval_transition_context(
                        action=Action(d.action), history=history, as_of=UtcTimestamp(now)
                    ),
                    reason_codes=("EXPLICIT_HUMAN_ACTION",),
                    occurred_at=UtcTimestamp(now),
                )
                state = target.value
                session.add(
                    DecisionApprovalRecord(
                        id=approval.id,
                        decision_id=d.id,
                        actor_id=actor,
                        action=action,
                        comment=comment,
                        expires_at=ttl.value if ttl else None,
                        created_at=now,
                        created_by=actor,
                        correlation_id=command.request_id,
                        metadata_json={},
                    )
                )
            else:
                if not isinstance(command, ManualExecutionCommand):
                    raise ValueError("MANUAL_COMMAND_REQUIRED")
                assert (
                    detail.approved_quantity is not None and detail.remaining_quantity is not None
                )
                if (
                    command.approval_id != detail.approval_id
                    or command.quantity > detail.remaining_quantity
                ):
                    raise ValueError("APPROVAL_OR_QUANTITY_MISMATCH")
                record = await session.get(DecisionApprovalRecord, command.approval_id)
                assert record is not None
                approval = _approval(record)
                when = command.executed_at.astimezone(UTC)
                if when > now or not approval.is_valid_at(UtcTimestamp(when)):
                    raise ValueError("EXECUTION_TIME_INVALID")
                sizing = await session.get(PositionSizingRunRecord, d.position_sizing_run_id)
                assert sizing is not None
                # No approved tolerance exists in V1 policy: only the exact approved reference.
                if command.price != Decimal(str(sizing.input_json["reference_price"])):
                    raise ValueError("PRICE_DRIFT_REQUIRES_NEW_DECISION")
                execution = DecisionExecution(
                    decision_id=d.id,
                    approval=approval,
                    mode=ExecutionMode.MANUAL,
                    status=ExecutionStatus.FILLED
                    if command.quantity == detail.remaining_quantity
                    else ExecutionStatus.PARTIAL,
                    requested_quantity=Quantity(detail.remaining_quantity),
                    filled_quantity=Quantity(command.quantity),
                    recorded_at=UtcTimestamp(now),
                    average_price=command.price,
                    external_references=(clean_text(command.external_reference),),
                )
                execution_id, approval_id = execution.id, approval.id
                state = (
                    "EXECUTED"
                    if command.quantity == detail.remaining_quantity
                    else "PARTIALLY_EXECUTED"
                )
                context = approval_transition_context(
                    action=Action(d.action),
                    history=DecisionApprovalHistory(d.id, (approval,)),
                    as_of=UtcTimestamp(now),
                    input_snapshot_matches=True,  # Recomputed ledger hash matched above.
                    price_within_tolerance=True,  # Exact approved reference matched above.
                )
                current = DecisionState(detail.decision.state)
                if current is DecisionState.APPROVED:
                    transition_decision(
                        current,
                        DecisionState.EXECUTION_PENDING,
                        context,
                        reason_codes=("EXPLICIT_MANUAL_FACT",),
                        occurred_at=UtcTimestamp(now),
                    )
                    current = DecisionState.EXECUTION_PENDING
                if current.value != state:
                    transition_decision(
                        current,
                        DecisionState(state),
                        replace(context, execution_recorded=True),
                        reason_codes=("EXPLICIT_MANUAL_FACT",),
                        occurred_at=UtcTimestamp(now),
                    )
                session.add(
                    DecisionExecutionRecord(
                        id=execution.id,
                        decision_id=d.id,
                        approval_id=approval.id,
                        execution_mode="MANUAL",
                        status=execution.status.value,
                        requested_quantity=execution.requested_quantity.value,
                        filled_quantity=execution.filled_quantity.value,
                        avg_price=execution.average_price,
                        external_refs_json=list(execution.external_references),
                        created_at=now,
                        created_by=actor,
                        correlation_id=command.request_id,
                        metadata_json={},
                    )
                )
                await session.flush()
                session.add(
                    ManualExecutionDetailRecord(
                        execution_id=execution.id,
                        fees=command.fees,
                        executed_at=when,
                        note=clean_text(command.note),
                    )
                )
            await session.flush()
            session.add(
                DecisionCenterActionRecord(
                    id=command.request_id,
                    decision_id=d.id,
                    revision=detail.decision.revision + 1,
                    action=action,
                    resulting_state=state,
                    actor_id=actor,
                    comment=comment,
                    command_hash=digest,
                    approval_id=approval_id,
                    execution_id=execution_id,
                    occurred_at=now,
                )
            )
            event_id = uuid4()
            payload = {
                "decision_id": str(d.id),
                "action": action,
                "revision": detail.decision.revision + 1,
                "state": state,
                "auto_trade": False,
                "broker_submitted": False,
            }
            session.add(
                EventLogRecord(
                    id=event_id,
                    event_type="DECISION_HUMAN_ACTION",
                    aggregate_type="InvestmentDecision",
                    aggregate_id=d.id,
                    payload_json=payload,
                    occurred_at=now,
                    correlation_id=command.request_id,
                    created_by=actor,
                )
            )
            await session.flush()
            session.add(
                OutboxEventRecord(
                    id=uuid4(),
                    event_id=event_id,
                    topic="decision.human-action",
                    payload_json=payload,
                    created_by=actor,
                    correlation_id=command.request_id,
                )
            )
            session.add(
                AuditLogRecord(
                    id=uuid4(),
                    actor_type="HUMAN",
                    actor_id=actor,
                    operation=action,
                    entity_type="InvestmentDecision",
                    entity_id=d.id,
                    before_hash=d.content_hash,
                    after_hash=digest,
                    ip_or_runtime_ref="decision-center",
                    occurred_at=now,
                    correlation_id=command.request_id,
                    created_by=actor,
                )
            )
            await session.flush()
            return await self._detail(session, d)


def _increases(d: InvestmentDecisionRecord) -> bool:
    try:
        return Decimal(str(d.position_after_proposed_json["total"])) > Decimal(
            str(d.position_before_json["total"])
        )
    except (KeyError, ValueError, ArithmeticError):
        return True


def _approval(record: DecisionApprovalRecord) -> DecisionApproval:
    return DecisionApproval(
        id=record.id,
        decision_id=record.decision_id,
        actor_id=record.actor_id,
        action=ApprovalAction(record.action),
        occurred_at=UtcTimestamp(record.created_at),
        expires_at=UtcTimestamp(record.expires_at) if record.expires_at else None,
        comment=record.comment,
    )


def _history(records: Sequence[DecisionApprovalRecord]) -> DecisionApprovalHistory:
    return DecisionApprovalHistory(records[0].decision_id, tuple(_approval(r) for r in records))
