"""Explicit, deterministic state machines for governed investment workflows."""

from dataclasses import dataclass
from enum import StrEnum

from investment_os.domain.enums import (
    Action,
    ActorType,
    DecisionState,
    InstrumentLifecycleState,
    StrategyProposalState,
    ThesisState,
)
from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.values import UtcTimestamp


@dataclass(frozen=True, slots=True)
class StateTransition[StateT: StrEnum]:
    from_state: StateT
    to_state: StateT
    reason_codes: tuple[str, ...]
    occurred_at: UtcTimestamp


def _start_transition[StateT: StrEnum](
    current: StateT,
    target: StateT,
    allowed: dict[StateT, frozenset[StateT]],
    reason_codes: tuple[str, ...],
) -> None:
    if not reason_codes or any(not reason.strip() for reason in reason_codes):
        raise DomainError(DomainErrorCode.REASON_REQUIRED, "transition requires reason codes")
    if target not in allowed.get(current, frozenset()):
        raise DomainError(
            DomainErrorCode.INVALID_TRANSITION,
            f"transition from {current.value} to {target.value} is not allowed",
            details={"from": current.value, "to": target.value},
        )


def _guard(condition: bool, message: str, *, code: DomainErrorCode | None = None) -> None:
    if not condition:
        raise DomainError(code or DomainErrorCode.TRANSITION_GUARD_FAILED, message)


INSTRUMENT_TRANSITIONS: dict[InstrumentLifecycleState, frozenset[InstrumentLifecycleState]] = {
    InstrumentLifecycleState.DISCOVER: frozenset({InstrumentLifecycleState.WATCH}),
    InstrumentLifecycleState.WATCH: frozenset({InstrumentLifecycleState.SETUP}),
    InstrumentLifecycleState.SETUP: frozenset({InstrumentLifecycleState.BUYABLE}),
    InstrumentLifecycleState.BUYABLE: frozenset({InstrumentLifecycleState.HOLD}),
    InstrumentLifecycleState.HOLD: frozenset(
        {
            InstrumentLifecycleState.ADD,
            InstrumentLifecycleState.REDUCE,
            InstrumentLifecycleState.EXIT,
        }
    ),
    InstrumentLifecycleState.ADD: frozenset(
        {InstrumentLifecycleState.HOLD, InstrumentLifecycleState.EXIT}
    ),
    InstrumentLifecycleState.REDUCE: frozenset(
        {InstrumentLifecycleState.HOLD, InstrumentLifecycleState.EXIT}
    ),
    InstrumentLifecycleState.EXIT: frozenset({InstrumentLifecycleState.COOLDOWN}),
    InstrumentLifecycleState.COOLDOWN: frozenset(
        {InstrumentLifecycleState.WATCH, InstrumentLifecycleState.ARCHIVED}
    ),
}


@dataclass(frozen=True, slots=True)
class InstrumentTransitionContext:
    screening_passed: bool = False
    data_sufficient: bool = False
    risk_passed: bool = False
    thesis_state: ThesisState = ThesisState.UNKNOWN
    observable_entry_condition: bool = False
    timing_confirmed: bool = False
    portfolio_capacity: bool = False
    policy_passed: bool = False
    human_approved: bool = False
    execution_recorded: bool = False
    reduction_justified: bool = False
    exit_justified: bool = False
    position_snapshot_updated: bool = False
    position_is_zero: bool = False
    review_date_recorded: bool = False
    cooldown_elapsed: bool = False
    new_evidence_or_thesis: bool = False
    archival_approved: bool = False


def transition_instrument(
    current: InstrumentLifecycleState,
    target: InstrumentLifecycleState,
    context: InstrumentTransitionContext,
    *,
    reason_codes: tuple[str, ...],
    occurred_at: UtcTimestamp,
) -> StateTransition[InstrumentLifecycleState]:
    _start_transition(current, target, INSTRUMENT_TRANSITIONS, reason_codes)

    if (current, target) == (InstrumentLifecycleState.DISCOVER, InstrumentLifecycleState.WATCH):
        _guard(context.screening_passed, "screening must pass")
        _guard(context.data_sufficient, "sufficient data is required")
        _guard(context.risk_passed, "Risk PASS is required")
    elif (current, target) == (InstrumentLifecycleState.WATCH, InstrumentLifecycleState.SETUP):
        _guard(
            context.thesis_state in {ThesisState.VALID, ThesisState.STRENGTHENING},
            "SETUP requires a VALID or STRENGTHENING thesis",
        )
        _guard(
            context.observable_entry_condition,
            "an observable catalyst or entry condition is required",
        )
    elif (current, target) == (InstrumentLifecycleState.SETUP, InstrumentLifecycleState.BUYABLE):
        _guard(context.timing_confirmed, "timing confirmation is required")
        _guard(context.portfolio_capacity, "portfolio capacity is required")
        _guard(context.risk_passed, "Risk PASS is required")
        _guard(context.policy_passed, "Policy PASS is required")
    elif (current, target) == (InstrumentLifecycleState.BUYABLE, InstrumentLifecycleState.HOLD):
        _guard(
            context.human_approved,
            "human approval is required",
            code=DomainErrorCode.HUMAN_APPROVAL_REQUIRED,
        )
        _guard(context.execution_recorded, "actual or simulated execution must be recorded")
    elif (current, target) == (InstrumentLifecycleState.HOLD, InstrumentLifecycleState.ADD):
        _guard(
            context.thesis_state not in {ThesisState.WEAKENING, ThesisState.BROKEN},
            "cannot ADD when thesis is WEAKENING or BROKEN",
        )
        _guard(context.risk_passed, "Risk PASS is required")
        _guard(context.policy_passed, "Policy PASS is required")
        _guard(context.portfolio_capacity, "deterministic sizing capacity is required")
    elif (current, target) == (InstrumentLifecycleState.HOLD, InstrumentLifecycleState.REDUCE):
        _guard(context.reduction_justified, "REDUCE requires a recorded justification")
    elif target is InstrumentLifecycleState.HOLD and current in {
        InstrumentLifecycleState.ADD,
        InstrumentLifecycleState.REDUCE,
    }:
        _guard(context.execution_recorded, "execution must be recorded")
        _guard(context.position_snapshot_updated, "position snapshot must be updated")
    elif target is InstrumentLifecycleState.EXIT:
        _guard(context.exit_justified, "EXIT requires a recorded justification")
    elif (current, target) == (InstrumentLifecycleState.EXIT, InstrumentLifecycleState.COOLDOWN):
        _guard(context.position_is_zero, "position must be zero or explicitly closed")
        _guard(context.review_date_recorded, "review date must be recorded")
    elif (current, target) == (InstrumentLifecycleState.COOLDOWN, InstrumentLifecycleState.WATCH):
        _guard(context.cooldown_elapsed, "cooldown must have elapsed")
        _guard(context.new_evidence_or_thesis, "new Evidence or a new Thesis is required")
    elif (current, target) == (
        InstrumentLifecycleState.COOLDOWN,
        InstrumentLifecycleState.ARCHIVED,
    ):
        _guard(context.archival_approved, "archival must be explicitly approved")

    return StateTransition(current, target, reason_codes, occurred_at)


THESIS_TRANSITIONS: dict[ThesisState, frozenset[ThesisState]] = {
    ThesisState.UNKNOWN: frozenset({ThesisState.VALID}),
    ThesisState.VALID: frozenset({ThesisState.STRENGTHENING, ThesisState.WEAKENING}),
    ThesisState.STRENGTHENING: frozenset({ThesisState.VALID, ThesisState.WEAKENING}),
    ThesisState.WEAKENING: frozenset({ThesisState.BROKEN}),
    ThesisState.BROKEN: frozenset({ThesisState.VALID}),
}


@dataclass(frozen=True, slots=True)
class ThesisTransitionContext:
    evidence_supports_change: bool = False
    creates_new_version: bool = False
    major_new_evidence: bool = False
    full_review_completed: bool = False


def transition_thesis(
    current: ThesisState,
    target: ThesisState,
    context: ThesisTransitionContext,
    *,
    reason_codes: tuple[str, ...],
    occurred_at: UtcTimestamp,
) -> StateTransition[ThesisState]:
    _start_transition(current, target, THESIS_TRANSITIONS, reason_codes)
    _guard(context.creates_new_version, "every thesis transition must create a new version")
    _guard(context.evidence_supports_change, "thesis transition requires supporting Evidence")
    if current is ThesisState.BROKEN and target is ThesisState.VALID:
        _guard(context.major_new_evidence, "BROKEN recovery requires major new Evidence")
        _guard(context.full_review_completed, "BROKEN recovery requires a full review")
    return StateTransition(current, target, reason_codes, occurred_at)


DECISION_TRANSITIONS: dict[DecisionState, frozenset[DecisionState]] = {
    DecisionState.DRAFT: frozenset({DecisionState.VALIDATED}),
    DecisionState.VALIDATED: frozenset({DecisionState.RISK_VETOED, DecisionState.PENDING_APPROVAL}),
    DecisionState.PENDING_APPROVAL: frozenset(
        {DecisionState.APPROVED, DecisionState.REJECTED, DecisionState.EXPIRED}
    ),
    DecisionState.APPROVED: frozenset({DecisionState.EXECUTION_PENDING, DecisionState.CANCELLED}),
    DecisionState.EXECUTION_PENDING: frozenset(
        {
            DecisionState.PARTIALLY_EXECUTED,
            DecisionState.EXECUTED,
            DecisionState.CANCELLED,
        }
    ),
    DecisionState.PARTIALLY_EXECUTED: frozenset({DecisionState.EXECUTED, DecisionState.CANCELLED}),
    DecisionState.EXECUTED: frozenset({DecisionState.REVIEW_DUE}),
    DecisionState.REVIEW_DUE: frozenset({DecisionState.REVIEWED}),
}


@dataclass(frozen=True, slots=True)
class DecisionTransitionContext:
    action: Action
    schema_valid: bool = False
    policy_passed: bool = False
    data_sufficient: bool = False
    risk_veto: bool = False
    risk_reduction_exception_recorded: bool = False
    approval_actor_type: ActorType | None = None
    approval_actor_id: str | None = None
    approval_recorded: bool = False
    approval_unexpired: bool = False
    approval_revoked: bool = False
    input_snapshot_matches: bool = False
    price_within_tolerance: bool = False
    execution_recorded: bool = False
    review_due: bool = False
    review_recorded: bool = False


def transition_decision(
    current: DecisionState,
    target: DecisionState,
    context: DecisionTransitionContext,
    *,
    reason_codes: tuple[str, ...],
    occurred_at: UtcTimestamp,
) -> StateTransition[DecisionState]:
    _start_transition(current, target, DECISION_TRANSITIONS, reason_codes)

    if (current, target) == (DecisionState.DRAFT, DecisionState.VALIDATED):
        _guard(context.schema_valid, "Decision Schema must be valid")
        _guard(context.policy_passed, "Policy Gate must pass")
        _guard(context.data_sufficient, "Decision requires sufficient data")
    elif (current, target) == (DecisionState.VALIDATED, DecisionState.RISK_VETOED):
        _guard(context.risk_veto, "RISK_VETOED requires an active Veto")
    elif (current, target) == (DecisionState.VALIDATED, DecisionState.PENDING_APPROVAL):
        if context.risk_veto:
            allowed_exception = (
                context.action in {Action.REDUCE, Action.EXIT}
                and context.risk_reduction_exception_recorded
            )
            _guard(
                allowed_exception,
                "Risk Veto blocks risk-increasing approval",
                code=DomainErrorCode.RISK_VETO_BLOCKED,
            )
    elif (current, target) == (DecisionState.PENDING_APPROVAL, DecisionState.APPROVED):
        valid_human = (
            context.approval_recorded
            and context.approval_actor_type is ActorType.HUMAN
            and bool(context.approval_actor_id and context.approval_actor_id.strip())
            and context.approval_unexpired
        )
        _guard(
            valid_human,
            "a valid, unexpired human approval is required",
            code=DomainErrorCode.APPROVAL_INVALID,
        )
    elif current is DecisionState.APPROVED and target is DecisionState.EXECUTION_PENDING:
        _guard(
            context.approval_unexpired,
            "expired approval cannot execute",
            code=DomainErrorCode.APPROVAL_INVALID,
        )
        _guard(
            not context.approval_revoked,
            "revoked approval cannot execute",
            code=DomainErrorCode.APPROVAL_INVALID,
        )
        _guard(context.input_snapshot_matches, "material input drift requires re-approval")
        _guard(context.price_within_tolerance, "price drift requires re-approval")
    elif current is DecisionState.APPROVED and target is DecisionState.CANCELLED:
        _guard(context.approval_revoked, "approved Decision cancellation requires revoked approval")
    elif target in {DecisionState.PARTIALLY_EXECUTED, DecisionState.EXECUTED}:
        _guard(context.execution_recorded, "execution transition requires an execution record")
    elif (current, target) == (DecisionState.EXECUTED, DecisionState.REVIEW_DUE):
        _guard(context.review_due, "review horizon has not matured")
    elif (current, target) == (DecisionState.REVIEW_DUE, DecisionState.REVIEWED):
        _guard(context.review_recorded, "review transition requires a review record")

    return StateTransition(current, target, reason_codes, occurred_at)


STRATEGY_TRANSITIONS: dict[StrategyProposalState, frozenset[StrategyProposalState]] = {
    StrategyProposalState.DRAFT: frozenset({StrategyProposalState.BACKTEST_PENDING}),
    StrategyProposalState.BACKTEST_PENDING: frozenset({StrategyProposalState.BACKTESTED}),
    StrategyProposalState.BACKTESTED: frozenset({StrategyProposalState.SHADOW_PENDING}),
    StrategyProposalState.SHADOW_PENDING: frozenset({StrategyProposalState.SHADOW_VALIDATED}),
    StrategyProposalState.SHADOW_VALIDATED: frozenset({StrategyProposalState.HUMAN_REVIEW}),
    StrategyProposalState.HUMAN_REVIEW: frozenset(
        {StrategyProposalState.APPROVED, StrategyProposalState.REJECTED}
    ),
    StrategyProposalState.APPROVED: frozenset({StrategyProposalState.SCHEDULED_ACTIVATION}),
    StrategyProposalState.SCHEDULED_ACTIVATION: frozenset({StrategyProposalState.ACTIVE}),
    StrategyProposalState.ACTIVE: frozenset({StrategyProposalState.RETIRED}),
}


@dataclass(frozen=True, slots=True)
class StrategyTransitionContext:
    actor_type: ActorType
    backtest_recorded: bool = False
    shadow_result_recorded: bool = False
    human_decision_recorded: bool = False
    activation_scheduled: bool = False
    activation_due: bool = False
    retirement_approved: bool = False


def transition_strategy_proposal(
    current: StrategyProposalState,
    target: StrategyProposalState,
    context: StrategyTransitionContext,
    *,
    reason_codes: tuple[str, ...],
    occurred_at: UtcTimestamp,
) -> StateTransition[StrategyProposalState]:
    _start_transition(current, target, STRATEGY_TRANSITIONS, reason_codes)
    if context.actor_type is ActorType.LEARNING_ENGINE and target in {
        StrategyProposalState.APPROVED,
        StrategyProposalState.REJECTED,
        StrategyProposalState.SCHEDULED_ACTIVATION,
        StrategyProposalState.ACTIVE,
        StrategyProposalState.RETIRED,
    }:
        raise DomainError(
            DomainErrorCode.LEARNING_AUTHORITY_EXCEEDED,
            "Learning Engine cannot approve, activate, reject, or retire a strategy",
        )

    if target is StrategyProposalState.BACKTESTED:
        _guard(context.backtest_recorded, "backtest result is required")
    elif target is StrategyProposalState.SHADOW_VALIDATED:
        _guard(context.shadow_result_recorded, "shadow result is required")
    elif current is StrategyProposalState.HUMAN_REVIEW:
        _guard(
            context.actor_type is ActorType.HUMAN,
            "strategy decision requires a human",
            code=DomainErrorCode.HUMAN_APPROVAL_REQUIRED,
        )
        _guard(context.human_decision_recorded, "human strategy decision must be recorded")
    elif target is StrategyProposalState.SCHEDULED_ACTIVATION:
        _guard(
            context.actor_type is ActorType.HUMAN,
            "activation scheduling requires a human",
            code=DomainErrorCode.HUMAN_APPROVAL_REQUIRED,
        )
        _guard(context.activation_scheduled, "activation schedule must be recorded")
    elif target is StrategyProposalState.ACTIVE:
        _guard(
            context.actor_type is ActorType.HUMAN,
            "activation requires human authority",
            code=DomainErrorCode.HUMAN_APPROVAL_REQUIRED,
        )
        _guard(context.activation_due, "strategy activation is not due")
    elif target is StrategyProposalState.RETIRED:
        _guard(
            context.actor_type is ActorType.HUMAN,
            "retirement requires human authority",
            code=DomainErrorCode.HUMAN_APPROVAL_REQUIRED,
        )
        _guard(context.retirement_approved, "strategy retirement must be approved")

    return StateTransition(current, target, reason_codes, occurred_at)
