"""Explicit CIO gate tests, including deferred S1/S2 final Action assertions."""

import pytest

from investment_os.application.decision_engine import (
    CioAggregationInput,
    CioGate,
    GateOutcome,
    aggregate_cio_recommendation,
)
from investment_os.domain.enums import Action, RiskGateState, ThesisState


def _inputs(**overrides: object) -> CioAggregationInput:
    values: dict[str, object] = {
        "proposed_action": Action.BUY,
        "investment_quality": GateOutcome.PASS,
        "thesis_state": ThesisState.VALID,
        "timing": GateOutcome.PASS,
        "portfolio_fit": GateOutcome.PASS,
        "risk_gate": RiskGateState.PASS,
        "policy_passed": True,
        "data_sufficient": True,
    }
    values.update(overrides)
    return CioAggregationInput(**values)  # type: ignore[arg-type]


def test_s1_good_investment_with_weak_timing_becomes_watch_not_buy() -> None:
    recommendation = aggregate_cio_recommendation(_inputs(timing=GateOutcome.FAIL))

    assert recommendation.action is Action.WATCH
    assert recommendation.outcome_for(CioGate.INVESTMENT_QUALITY) is GateOutcome.PASS
    assert recommendation.outcome_for(CioGate.TIMING) is GateOutcome.FAIL


@pytest.mark.parametrize("quality", (GateOutcome.FAIL, GateOutcome.UNKNOWN))
def test_s2_strong_timing_cannot_override_weak_or_unknown_investment(quality: GateOutcome) -> None:
    recommendation = aggregate_cio_recommendation(
        _inputs(investment_quality=quality, thesis_state=ThesisState.UNKNOWN)
    )

    assert recommendation.action is Action.AVOID
    assert recommendation.outcome_for(CioGate.TIMING) is GateOutcome.PASS
    assert recommendation.outcome_for(CioGate.INVESTMENT_QUALITY) is quality


@pytest.mark.parametrize(
    "overrides",
    (
        {"portfolio_fit": GateOutcome.FAIL},
        {"risk_gate": RiskGateState.VETO},
        {"policy_passed": False},
        {"data_sufficient": False},
    ),
)
def test_risk_or_other_required_gate_cannot_produce_increased_exposure(
    overrides: dict[str, object],
) -> None:
    recommendation = aggregate_cio_recommendation(_inputs(**overrides))

    assert recommendation.action is Action.WATCH


def test_all_explicit_gates_pass_before_buy_is_preserved() -> None:
    recommendation = aggregate_cio_recommendation(_inputs())

    assert recommendation.action is Action.BUY
    assert tuple(result.gate for result in recommendation.gates) == tuple(CioGate)
    assert all(result.outcome is GateOutcome.PASS for result in recommendation.gates)


@pytest.mark.parametrize("action", (Action.REDUCE, Action.EXIT))
def test_risk_reducing_actions_remain_available_despite_veto(action: Action) -> None:
    recommendation = aggregate_cio_recommendation(
        _inputs(
            proposed_action=action,
            investment_quality=GateOutcome.FAIL,
            thesis_state=ThesisState.BROKEN,
            timing=GateOutcome.FAIL,
            portfolio_fit=GateOutcome.FAIL,
            risk_gate=RiskGateState.VETO,
            policy_passed=False,
            data_sufficient=False,
        )
    )

    assert recommendation.action is action
    assert recommendation.outcome_for(CioGate.RISK) is GateOutcome.FAIL
