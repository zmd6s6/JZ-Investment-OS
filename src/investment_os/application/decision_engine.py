"""Deterministic CIO Action gating without a composite-score trading path."""

from dataclasses import dataclass
from enum import StrEnum

from investment_os.domain.enums import Action, RiskGateState, ThesisState


class GateOutcome(StrEnum):
    """Closed outcome vocabulary for one independently auditable CIO gate."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class CioGate(StrEnum):
    INVESTMENT_QUALITY = "INVESTMENT_QUALITY"
    THESIS = "THESIS"
    TIMING = "TIMING"
    PORTFOLIO_FIT = "PORTFOLIO_FIT"
    RISK = "RISK"
    POLICY = "POLICY"
    DATA_SUFFICIENCY = "DATA_SUFFICIENCY"


@dataclass(frozen=True, slots=True)
class CioGateResult:
    gate: CioGate
    outcome: GateOutcome
    reason_code: str


@dataclass(frozen=True, slots=True)
class CioAggregationInput:
    """Already-validated deterministic/structured inputs; never raw model text."""

    proposed_action: Action
    investment_quality: GateOutcome
    thesis_state: ThesisState
    timing: GateOutcome
    portfolio_fit: GateOutcome
    risk_gate: RiskGateState
    policy_passed: bool
    data_sufficient: bool


@dataclass(frozen=True, slots=True)
class CioRecommendation:
    """A final Action accompanied by every individual gate result."""

    action: Action
    gates: tuple[CioGateResult, ...]

    def outcome_for(self, gate: CioGate) -> GateOutcome:
        return next(result.outcome for result in self.gates if result.gate is gate)


def aggregate_cio_recommendation(inputs: CioAggregationInput) -> CioRecommendation:
    """Apply explicit, ordered gates; this deliberately contains no additive score.

    BUY and ADD require every gate to pass. Good investment quality with weak/unknown timing is
    WATCH. Weak or unknown investment quality/Thesis is AVOID even when timing is strong. Risk
    reduction never depends on permissions for new exposure.
    """

    gates = _gate_results(inputs)
    outcomes = {result.gate: result.outcome for result in gates}

    if inputs.proposed_action in {Action.REDUCE, Action.EXIT}:
        return CioRecommendation(action=inputs.proposed_action, gates=gates)
    if inputs.proposed_action not in {Action.BUY, Action.ADD}:
        return CioRecommendation(action=inputs.proposed_action, gates=gates)

    if outcomes[CioGate.INVESTMENT_QUALITY] is not GateOutcome.PASS:
        return CioRecommendation(action=Action.AVOID, gates=gates)
    if outcomes[CioGate.THESIS] is not GateOutcome.PASS:
        return CioRecommendation(action=Action.AVOID, gates=gates)
    if outcomes[CioGate.TIMING] is not GateOutcome.PASS:
        return CioRecommendation(action=Action.WATCH, gates=gates)
    if any(
        outcomes[gate] is not GateOutcome.PASS
        for gate in (
            CioGate.PORTFOLIO_FIT,
            CioGate.RISK,
            CioGate.POLICY,
            CioGate.DATA_SUFFICIENCY,
        )
    ):
        return CioRecommendation(action=Action.WATCH, gates=gates)
    return CioRecommendation(action=inputs.proposed_action, gates=gates)


def _gate_results(inputs: CioAggregationInput) -> tuple[CioGateResult, ...]:
    return (
        CioGateResult(
            CioGate.INVESTMENT_QUALITY,
            inputs.investment_quality,
            f"CIO_INVESTMENT_QUALITY_{inputs.investment_quality.value}",
        ),
        CioGateResult(CioGate.THESIS, _thesis_outcome(inputs.thesis_state), _thesis_reason(inputs)),
        CioGateResult(CioGate.TIMING, inputs.timing, f"CIO_TIMING_{inputs.timing.value}"),
        CioGateResult(
            CioGate.PORTFOLIO_FIT,
            inputs.portfolio_fit,
            f"CIO_PORTFOLIO_FIT_{inputs.portfolio_fit.value}",
        ),
        CioGateResult(CioGate.RISK, _risk_outcome(inputs.risk_gate), _risk_reason(inputs)),
        CioGateResult(
            CioGate.POLICY,
            GateOutcome.PASS if inputs.policy_passed else GateOutcome.FAIL,
            "CIO_POLICY_PASS" if inputs.policy_passed else "CIO_POLICY_FAIL",
        ),
        CioGateResult(
            CioGate.DATA_SUFFICIENCY,
            GateOutcome.PASS if inputs.data_sufficient else GateOutcome.UNKNOWN,
            "CIO_DATA_SUFFICIENT" if inputs.data_sufficient else "CIO_DATA_INSUFFICIENT",
        ),
    )


def _thesis_outcome(state: ThesisState) -> GateOutcome:
    if state in {ThesisState.VALID, ThesisState.STRENGTHENING}:
        return GateOutcome.PASS
    if state in {ThesisState.WEAKENING, ThesisState.BROKEN}:
        return GateOutcome.FAIL
    return GateOutcome.UNKNOWN


def _thesis_reason(inputs: CioAggregationInput) -> str:
    return f"CIO_THESIS_{inputs.thesis_state.value}"


def _risk_outcome(gate: RiskGateState) -> GateOutcome:
    if gate is RiskGateState.PASS:
        return GateOutcome.PASS
    if gate is RiskGateState.VETO:
        return GateOutcome.FAIL
    return GateOutcome.UNKNOWN


def _risk_reason(inputs: CioAggregationInput) -> str:
    return f"CIO_RISK_{inputs.risk_gate.value}"
