"""Evidence-first immutable Decision aggregate tests."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from investment_os.domain.decision import DecisionClaim, DecisionPosition, InvestmentDecision
from investment_os.domain.enums import Action, BucketAction, RiskIntent
from investment_os.domain.errors import DomainError
from investment_os.domain.values import UtcTimestamp, Weight

NOW = UtcTimestamp(datetime(2026, 9, 20, tzinfo=UTC))


def _position(core: str = "0.03", tactical: str = "0.02") -> DecisionPosition:
    return DecisionPosition(
        total=Weight(Decimal(core) + Decimal(tactical)),
        core=Weight(Decimal(core)),
        tactical=Weight(Decimal(tactical)),
    )


def _decision(**overrides: object) -> InvestmentDecision:
    evidence_id = uuid4()
    values: dict[str, object] = {
        "instrument_id": uuid4(),
        "portfolio_id": uuid4(),
        "thesis_version_id": uuid4(),
        "policy_version_id": uuid4(),
        "strategy_version_id": uuid4(),
        "risk_assessment_id": uuid4(),
        "position_sizing_run_id": uuid4(),
        "action": Action.BUY,
        "confidence": Weight(Decimal("0.7")),
        "risk_intent": RiskIntent.SMALL,
        "position_before": _position("0.00", "0.00"),
        "position_after_proposed": _position(),
        "core_action": BucketAction.BUY,
        "tactical_action": BucketAction.BUY,
        "reasons": (DecisionClaim("Synthetic evidence-backed reason", (evidence_id,)),),
        "risks": (DecisionClaim("Synthetic evidence-backed risk", (evidence_id,)),),
        "watch_conditions": ("Synthetic timing confirmation",),
        "invalidation_conditions": ("Synthetic thesis invalidation",),
        "unknowns": ("Synthetic unknown",),
        "dissent": ("Synthetic dissent",),
        "next_review_at": NOW,
        "input_snapshot_hash": "a" * 64,
        "prompt_bundle_version": "synthetic-prompt-v1",
        "formula_version": "synthetic-sizing-v1",
    }
    values.update(overrides)
    return InvestmentDecision(**values)  # type: ignore[arg-type]


def test_decision_preserves_auditable_evidence_versions_and_core_tactical_actions() -> None:
    decision = _decision()

    assert len(decision.evidence_ids) == 1
    assert decision.core_action is BucketAction.BUY
    assert decision.tactical_action is BucketAction.BUY
    assert len(decision.content_hash) == 64
    assert decision.content_hash == replace(decision, id=uuid4()).content_hash


@pytest.mark.parametrize(
    ("action", "core_action", "tactical_action"),
    (
        (Action.WATCH, BucketAction.BUY, BucketAction.NONE),
        (Action.AVOID, BucketAction.NONE, BucketAction.HOLD),
        (Action.BUY, BucketAction.NONE, BucketAction.NONE),
        (Action.REDUCE, BucketAction.HOLD, BucketAction.NONE),
    ),
)
def test_decision_rejects_action_that_hides_or_misstates_bucket_effect(
    action: Action,
    core_action: BucketAction,
    tactical_action: BucketAction,
) -> None:
    with pytest.raises(DomainError):
        _decision(action=action, core_action=core_action, tactical_action=tactical_action)


def test_decision_rejects_unproven_claims_bad_hash_and_unreconciled_positions() -> None:
    with pytest.raises(DomainError, match="Evidence"):
        DecisionClaim("Synthetic unsupported claim", ())
    with pytest.raises(DomainError, match="64-character"):
        _decision(input_snapshot_hash="bad")
    with pytest.raises(DomainError, match="Core plus Tactical"):
        DecisionPosition(
            total=Weight(Decimal("0.06")),
            core=Weight(Decimal("0.03")),
            tactical=Weight(Decimal("0.02")),
        )
