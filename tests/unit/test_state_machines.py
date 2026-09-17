from datetime import UTC, datetime

import pytest

from investment_os.domain.enums import (
    Action,
    ActorType,
    DecisionState,
    InstrumentLifecycleState,
    RiskGateState,
    StrategyProposalState,
    ThesisState,
)
from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.state_machines import (
    DecisionTransitionContext,
    InstrumentTransitionContext,
    StrategyTransitionContext,
    ThesisTransitionContext,
    transition_decision,
    transition_instrument,
    transition_strategy_proposal,
    transition_thesis,
)
from investment_os.domain.values import UtcTimestamp

NOW = UtcTimestamp(datetime(2026, 9, 17, tzinfo=UTC))
REASONS = ("TEST_REASON",)


@pytest.mark.parametrize(
    ("current", "target", "context"),
    [
        (
            InstrumentLifecycleState.DISCOVER,
            InstrumentLifecycleState.WATCH,
            InstrumentTransitionContext(
                screening_passed=True, data_sufficient=True, risk_passed=True
            ),
        ),
        (
            InstrumentLifecycleState.WATCH,
            InstrumentLifecycleState.SETUP,
            InstrumentTransitionContext(
                thesis_state=ThesisState.VALID, observable_entry_condition=True
            ),
        ),
        (
            InstrumentLifecycleState.SETUP,
            InstrumentLifecycleState.BUYABLE,
            InstrumentTransitionContext(
                timing_confirmed=True,
                portfolio_capacity=True,
                risk_passed=True,
                policy_passed=True,
            ),
        ),
        (
            InstrumentLifecycleState.BUYABLE,
            InstrumentLifecycleState.HOLD,
            InstrumentTransitionContext(human_approved=True, execution_recorded=True),
        ),
        (
            InstrumentLifecycleState.HOLD,
            InstrumentLifecycleState.ADD,
            InstrumentTransitionContext(
                thesis_state=ThesisState.VALID,
                risk_passed=True,
                policy_passed=True,
                portfolio_capacity=True,
            ),
        ),
        (
            InstrumentLifecycleState.HOLD,
            InstrumentLifecycleState.REDUCE,
            InstrumentTransitionContext(reduction_justified=True),
        ),
        (
            InstrumentLifecycleState.ADD,
            InstrumentLifecycleState.HOLD,
            InstrumentTransitionContext(execution_recorded=True, position_snapshot_updated=True),
        ),
        (
            InstrumentLifecycleState.REDUCE,
            InstrumentLifecycleState.HOLD,
            InstrumentTransitionContext(execution_recorded=True, position_snapshot_updated=True),
        ),
        (
            InstrumentLifecycleState.HOLD,
            InstrumentLifecycleState.EXIT,
            InstrumentTransitionContext(exit_justified=True),
        ),
        (
            InstrumentLifecycleState.ADD,
            InstrumentLifecycleState.EXIT,
            InstrumentTransitionContext(exit_justified=True),
        ),
        (
            InstrumentLifecycleState.EXIT,
            InstrumentLifecycleState.COOLDOWN,
            InstrumentTransitionContext(position_is_zero=True, review_date_recorded=True),
        ),
        (
            InstrumentLifecycleState.COOLDOWN,
            InstrumentLifecycleState.WATCH,
            InstrumentTransitionContext(cooldown_elapsed=True, new_evidence_or_thesis=True),
        ),
        (
            InstrumentLifecycleState.COOLDOWN,
            InstrumentLifecycleState.ARCHIVED,
            InstrumentTransitionContext(archival_approved=True),
        ),
    ],
)
def test_instrument_legal_transitions_succeed(
    current: InstrumentLifecycleState,
    target: InstrumentLifecycleState,
    context: InstrumentTransitionContext,
) -> None:
    transition = transition_instrument(
        current, target, context, reason_codes=REASONS, occurred_at=NOW
    )
    assert transition.from_state is current
    assert transition.to_state is target


def test_instrument_add_fails_when_thesis_is_weakening() -> None:
    with pytest.raises(DomainError, match="WEAKENING or BROKEN"):
        transition_instrument(
            InstrumentLifecycleState.HOLD,
            InstrumentLifecycleState.ADD,
            InstrumentTransitionContext(
                thesis_state=ThesisState.WEAKENING,
                risk_passed=True,
                policy_passed=True,
                portfolio_capacity=True,
            ),
            reason_codes=REASONS,
            occurred_at=NOW,
        )


def test_instrument_buyable_to_hold_requires_human_approval() -> None:
    with pytest.raises(DomainError) as caught:
        transition_instrument(
            InstrumentLifecycleState.BUYABLE,
            InstrumentLifecycleState.HOLD,
            InstrumentTransitionContext(execution_recorded=True),
            reason_codes=REASONS,
            occurred_at=NOW,
        )
    assert caught.value.code is DomainErrorCode.HUMAN_APPROVAL_REQUIRED


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ThesisState.UNKNOWN, ThesisState.VALID),
        (ThesisState.VALID, ThesisState.STRENGTHENING),
        (ThesisState.VALID, ThesisState.WEAKENING),
        (ThesisState.STRENGTHENING, ThesisState.VALID),
        (ThesisState.STRENGTHENING, ThesisState.WEAKENING),
        (ThesisState.WEAKENING, ThesisState.BROKEN),
    ],
)
def test_thesis_legal_transitions_create_new_evidence_backed_version(
    current: ThesisState, target: ThesisState
) -> None:
    transition = transition_thesis(
        current,
        target,
        ThesisTransitionContext(evidence_supports_change=True, creates_new_version=True),
        reason_codes=REASONS,
        occurred_at=NOW,
    )
    assert transition.to_state is target


def test_broken_thesis_recovery_requires_major_evidence_and_full_review() -> None:
    context = ThesisTransitionContext(
        evidence_supports_change=True,
        creates_new_version=True,
        major_new_evidence=True,
        full_review_completed=True,
    )
    assert (
        transition_thesis(
            ThesisState.BROKEN,
            ThesisState.VALID,
            context,
            reason_codes=REASONS,
            occurred_at=NOW,
        ).to_state
        is ThesisState.VALID
    )


def test_broken_thesis_cannot_recover_without_full_review() -> None:
    with pytest.raises(DomainError, match="full review"):
        transition_thesis(
            ThesisState.BROKEN,
            ThesisState.VALID,
            ThesisTransitionContext(
                evidence_supports_change=True,
                creates_new_version=True,
                major_new_evidence=True,
            ),
            reason_codes=REASONS,
            occurred_at=NOW,
        )


def test_buy_without_risk_assessment_cannot_enter_pending_approval() -> None:
    with pytest.raises(DomainError) as caught:
        transition_decision(
            DecisionState.VALIDATED,
            DecisionState.PENDING_APPROVAL,
            DecisionTransitionContext(action=Action.BUY),
            reason_codes=REASONS,
            occurred_at=NOW,
        )
    assert caught.value.code is DomainErrorCode.RISK_ASSESSMENT_REQUIRED


def test_buy_with_explicit_risk_pass_can_enter_pending_approval() -> None:
    transition = transition_decision(
        DecisionState.VALIDATED,
        DecisionState.PENDING_APPROVAL,
        DecisionTransitionContext(action=Action.BUY, risk_gate=RiskGateState.PASS),
        reason_codes=REASONS,
        occurred_at=NOW,
    )
    assert transition.to_state is DecisionState.PENDING_APPROVAL


def test_add_requires_explicit_risk_pass() -> None:
    with pytest.raises(DomainError) as caught:
        transition_decision(
            DecisionState.VALIDATED,
            DecisionState.PENDING_APPROVAL,
            DecisionTransitionContext(action=Action.ADD),
            reason_codes=REASONS,
            occurred_at=NOW,
        )
    assert caught.value.code is DomainErrorCode.RISK_ASSESSMENT_REQUIRED

    transition = transition_decision(
        DecisionState.VALIDATED,
        DecisionState.PENDING_APPROVAL,
        DecisionTransitionContext(action=Action.ADD, risk_gate=RiskGateState.PASS),
        reason_codes=REASONS,
        occurred_at=NOW,
    )
    assert transition.to_state is DecisionState.PENDING_APPROVAL


def test_buy_decision_cannot_pass_risk_veto() -> None:
    with pytest.raises(DomainError) as caught:
        transition_decision(
            DecisionState.VALIDATED,
            DecisionState.PENDING_APPROVAL,
            DecisionTransitionContext(action=Action.BUY, risk_gate=RiskGateState.VETO),
            reason_codes=REASONS,
            occurred_at=NOW,
        )
    assert caught.value.code is DomainErrorCode.RISK_VETO_BLOCKED


@pytest.mark.parametrize("action", [Action.REDUCE, Action.EXIT])
def test_risk_reducing_decision_can_proceed_under_recorded_veto_exception(
    action: Action,
) -> None:
    transition = transition_decision(
        DecisionState.VALIDATED,
        DecisionState.PENDING_APPROVAL,
        DecisionTransitionContext(
            action=action,
            risk_gate=RiskGateState.VETO,
            risk_reduction_exception_recorded=True,
        ),
        reason_codes=REASONS,
        occurred_at=NOW,
    )
    assert transition.to_state is DecisionState.PENDING_APPROVAL


@pytest.mark.parametrize("action", [Action.REDUCE, Action.EXIT])
def test_risk_reducing_decision_under_veto_requires_recorded_exception(
    action: Action,
) -> None:
    with pytest.raises(DomainError) as caught:
        transition_decision(
            DecisionState.VALIDATED,
            DecisionState.PENDING_APPROVAL,
            DecisionTransitionContext(action=action, risk_gate=RiskGateState.VETO),
            reason_codes=REASONS,
            occurred_at=NOW,
        )
    assert caught.value.code is DomainErrorCode.RISK_VETO_BLOCKED


def test_decision_requires_valid_human_approval() -> None:
    with pytest.raises(DomainError) as caught:
        transition_decision(
            DecisionState.PENDING_APPROVAL,
            DecisionState.APPROVED,
            DecisionTransitionContext(
                action=Action.BUY,
                approval_actor_type=ActorType.SYSTEM,
                approval_actor_id="system",
                approval_recorded=True,
                approval_unexpired=True,
            ),
            reason_codes=REASONS,
            occurred_at=NOW,
        )
    assert caught.value.code is DomainErrorCode.APPROVAL_INVALID


def test_approved_decision_fails_closed_on_material_input_drift() -> None:
    with pytest.raises(DomainError, match="input drift"):
        transition_decision(
            DecisionState.APPROVED,
            DecisionState.EXECUTION_PENDING,
            DecisionTransitionContext(
                action=Action.BUY,
                approval_unexpired=True,
                input_snapshot_matches=False,
                price_within_tolerance=True,
            ),
            reason_codes=REASONS,
            occurred_at=NOW,
        )


def test_decision_full_happy_path() -> None:
    contexts = [
        (
            DecisionState.DRAFT,
            DecisionState.VALIDATED,
            DecisionTransitionContext(
                action=Action.BUY,
                schema_valid=True,
                policy_passed=True,
                data_sufficient=True,
            ),
        ),
        (
            DecisionState.VALIDATED,
            DecisionState.PENDING_APPROVAL,
            DecisionTransitionContext(action=Action.BUY, risk_gate=RiskGateState.PASS),
        ),
        (
            DecisionState.PENDING_APPROVAL,
            DecisionState.APPROVED,
            DecisionTransitionContext(
                action=Action.BUY,
                approval_actor_type=ActorType.HUMAN,
                approval_actor_id="owner",
                approval_recorded=True,
                approval_unexpired=True,
            ),
        ),
        (
            DecisionState.APPROVED,
            DecisionState.EXECUTION_PENDING,
            DecisionTransitionContext(
                action=Action.BUY,
                approval_unexpired=True,
                input_snapshot_matches=True,
                price_within_tolerance=True,
            ),
        ),
        (
            DecisionState.EXECUTION_PENDING,
            DecisionState.PARTIALLY_EXECUTED,
            DecisionTransitionContext(action=Action.BUY, execution_recorded=True),
        ),
        (
            DecisionState.PARTIALLY_EXECUTED,
            DecisionState.EXECUTED,
            DecisionTransitionContext(action=Action.BUY, execution_recorded=True),
        ),
        (
            DecisionState.EXECUTED,
            DecisionState.REVIEW_DUE,
            DecisionTransitionContext(action=Action.BUY, review_due=True),
        ),
        (
            DecisionState.REVIEW_DUE,
            DecisionState.REVIEWED,
            DecisionTransitionContext(action=Action.BUY, review_recorded=True),
        ),
    ]
    for current, target, context in contexts:
        assert (
            transition_decision(
                current, target, context, reason_codes=REASONS, occurred_at=NOW
            ).to_state
            is target
        )


def test_risk_veto_state_requires_active_veto() -> None:
    with pytest.raises(DomainError):
        transition_decision(
            DecisionState.VALIDATED,
            DecisionState.RISK_VETOED,
            DecisionTransitionContext(action=Action.ADD),
            reason_codes=REASONS,
            occurred_at=NOW,
        )


def test_revoked_approval_can_only_cancel() -> None:
    transition = transition_decision(
        DecisionState.APPROVED,
        DecisionState.CANCELLED,
        DecisionTransitionContext(action=Action.BUY, approval_revoked=True),
        reason_codes=REASONS,
        occurred_at=NOW,
    )
    assert transition.to_state is DecisionState.CANCELLED


def test_learning_engine_cannot_approve_strategy() -> None:
    with pytest.raises(DomainError) as caught:
        transition_strategy_proposal(
            StrategyProposalState.HUMAN_REVIEW,
            StrategyProposalState.APPROVED,
            StrategyTransitionContext(
                actor_type=ActorType.LEARNING_ENGINE, human_decision_recorded=True
            ),
            reason_codes=REASONS,
            occurred_at=NOW,
        )
    assert caught.value.code is DomainErrorCode.LEARNING_AUTHORITY_EXCEEDED


def test_strategy_proposal_full_governed_path() -> None:
    steps = [
        (
            StrategyProposalState.DRAFT,
            StrategyProposalState.BACKTEST_PENDING,
            StrategyTransitionContext(actor_type=ActorType.LEARNING_ENGINE),
        ),
        (
            StrategyProposalState.BACKTEST_PENDING,
            StrategyProposalState.BACKTESTED,
            StrategyTransitionContext(actor_type=ActorType.LEARNING_ENGINE, backtest_recorded=True),
        ),
        (
            StrategyProposalState.BACKTESTED,
            StrategyProposalState.SHADOW_PENDING,
            StrategyTransitionContext(actor_type=ActorType.LEARNING_ENGINE),
        ),
        (
            StrategyProposalState.SHADOW_PENDING,
            StrategyProposalState.SHADOW_VALIDATED,
            StrategyTransitionContext(
                actor_type=ActorType.LEARNING_ENGINE, shadow_result_recorded=True
            ),
        ),
        (
            StrategyProposalState.SHADOW_VALIDATED,
            StrategyProposalState.HUMAN_REVIEW,
            StrategyTransitionContext(actor_type=ActorType.LEARNING_ENGINE),
        ),
        (
            StrategyProposalState.HUMAN_REVIEW,
            StrategyProposalState.APPROVED,
            StrategyTransitionContext(actor_type=ActorType.HUMAN, human_decision_recorded=True),
        ),
        (
            StrategyProposalState.APPROVED,
            StrategyProposalState.SCHEDULED_ACTIVATION,
            StrategyTransitionContext(actor_type=ActorType.HUMAN, activation_scheduled=True),
        ),
        (
            StrategyProposalState.SCHEDULED_ACTIVATION,
            StrategyProposalState.ACTIVE,
            StrategyTransitionContext(actor_type=ActorType.HUMAN, activation_due=True),
        ),
        (
            StrategyProposalState.ACTIVE,
            StrategyProposalState.RETIRED,
            StrategyTransitionContext(actor_type=ActorType.HUMAN, retirement_approved=True),
        ),
    ]
    for current, target, context in steps:
        assert (
            transition_strategy_proposal(
                current, target, context, reason_codes=REASONS, occurred_at=NOW
            ).to_state
            is target
        )


def test_transition_requires_machine_readable_reason() -> None:
    with pytest.raises(DomainError) as caught:
        transition_thesis(
            ThesisState.UNKNOWN,
            ThesisState.VALID,
            ThesisTransitionContext(evidence_supports_change=True, creates_new_version=True),
            reason_codes=(),
            occurred_at=NOW,
        )
    assert caught.value.code is DomainErrorCode.REASON_REQUIRED


def test_illegal_transition_fails_closed() -> None:
    with pytest.raises(DomainError) as caught:
        transition_instrument(
            InstrumentLifecycleState.DISCOVER,
            InstrumentLifecycleState.HOLD,
            InstrumentTransitionContext(),
            reason_codes=REASONS,
            occurred_at=NOW,
        )
    assert caught.value.code is DomainErrorCode.INVALID_TRANSITION
