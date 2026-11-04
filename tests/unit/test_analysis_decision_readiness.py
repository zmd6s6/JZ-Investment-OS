"""Synthetic, explicit Strategy qualification; no tests choose real investment parameters."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from investment_os.application.analysis_decision_bridge import (
    DecisionBridgeScope,
    DecisionGateFact,
    DecisionGateRule,
    DecisionQualification,
    StrategyDecisionRules,
    StrategyDecisionSnapshot,
    evaluate_decision_readiness,
)
from investment_os.application.analysis_risk_sizing import RiskSizingView
from investment_os.domain.enums import Action


def complete():
    now = datetime(2026, 11, 4, tzinfo=UTC)
    ids = {name: uuid4() for name in ("portfolio", "instrument", "policy", "numeric", "strategy")}
    rules = StrategyDecisionRules(
        schema_version="strategy-decision-rules-1.0",
        allow_decision_proposals=True,
        simulation_only=True,
        portfolio_ids=(ids["portfolio"],),
        instrument_ids=(ids["instrument"],),
        valid_from=now - timedelta(days=1),
        valid_until=now + timedelta(days=1),
        review_after_seconds=600,
        gates={
            name: (DecisionGateRule(metric=name, comparison="GTE", threshold="1"),)
            for name in ("INVESTMENT_QUALITY", "TIMING", "PORTFOLIO_FIT")
        },
    )
    strategy = StrategyDecisionSnapshot(
        strategy_version_id=ids["strategy"],
        version=1,
        status="ACTIVE",
        approved_by="explicit-synthetic-human",
        approved_by_actor="HUMAN",
        approved_at=now - timedelta(hours=1),
        prompt_bundle_hash="a" * 64,
        code_ref="synthetic-206-only",
        rules=rules,
        content_hash="0" * 64,
    )
    strategy = strategy.model_copy(update={"content_hash": strategy.expected_content_hash()})
    source = DecisionQualification(
        schema_version="decision-qualification-1.0",
        qualification_id=uuid4(),
        portfolio_id=ids["portfolio"],
        instrument_id=ids["instrument"],
        policy_version_id=ids["policy"],
        numeric_snapshot_id=ids["numeric"],
        portfolio_identity_hash="b" * 64,
        strategy_version_id=ids["strategy"],
        strategy_content_hash=strategy.content_hash,
        source_kind="SYNTHETIC_FIXTURE",
        source_name="explicit-synthetic-206-qualification",
        as_of=now - timedelta(minutes=1),
        created_at=now - timedelta(seconds=30),
        expires_at=now + timedelta(hours=1),
        facts=tuple(
            DecisionGateFact(
                metric=name, value="1", evidence_id=uuid4(), evidence_content_hash="c" * 64
            )
            for name in rules.gates
        ),
        content_hash="0" * 64,
    )
    source = source.model_copy(update={"content_hash": source.expected_content_hash()})
    scope = DecisionBridgeScope(
        portfolio_id=ids["portfolio"],
        instrument_id=ids["instrument"],
        policy_version_id=ids["policy"],
        numeric_snapshot_id=ids["numeric"],
        portfolio_identity_hash="b" * 64,
        captured_at=now,
        queued_at=now,
        scheduled_shadow=False,
    )
    numeric = RiskSizingView(
        risk_gate="PASS",
        sizing_status="COMPUTED",
        numeric_snapshot_id=ids["numeric"],
        policy_version_id=ids["policy"],
        risk_assessment_id=uuid4(),
        sizing_run_id=uuid4(),
        evaluated_at=now,
        expires_at=now + timedelta(hours=1),
    )
    return dict(
        scope=scope,
        qualification=source,
        strategy=strategy,
        numeric=numeric,
        action=Action.ADD,
        evaluated_at=now,
    )


def test_complete_explicit_synthetic_rules_are_ready_for_reconstruction_only():
    result = evaluate_decision_readiness(**complete())
    assert result.status == "READY_FOR_RECONSTRUCTION" and not result.blockers
    assert all(gate.value == "PASS" for gate in result.gates.values())
    assert result.decision_id is None and result.execution_allowed is result.auto_trade is False


@pytest.mark.parametrize("key", ["qualification", "strategy", "numeric"])
def test_missing_qualification_strategy_or_numeric_never_infers_permission(key):
    data = complete()
    data[key] = None
    result = evaluate_decision_readiness(**data)
    assert result.status == "BLOCKED" and result.blockers


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("source_kind", "REFERENCE_ONLY", "DECISION_REFERENCE_SOURCE_NOT_QUALIFIED"),
        ("content_hash", "e" * 64, "DECISION_QUALIFICATION_HASH_MISMATCH"),
        ("portfolio_id", uuid4(), "DECISION_QUALIFICATION_SCOPE_MISMATCH"),
        ("numeric_snapshot_id", uuid4(), "DECISION_QUALIFICATION_SCOPE_MISMATCH"),
        ("strategy_version_id", uuid4(), "DECISION_FIXED_STRATEGY_MISMATCH"),
    ],
)
def test_reference_corruption_or_identity_mismatch_is_blocked(field, value, reason):
    data = complete()
    data["qualification"] = data["qualification"].model_copy(update={field: value})
    result = evaluate_decision_readiness(**data)
    assert reason in result.blockers and result.status == "BLOCKED"


@pytest.mark.parametrize("offset,allowed", [(-1, True), (0, False), (1, False)])
def test_qualification_expiry_is_half_open_at_the_actual_final_evaluation(offset, allowed):
    data = complete()
    data["qualification"] = data["qualification"].model_copy(
        update={"expires_at": data["evaluated_at"] + timedelta(seconds=1)}
    )
    data["qualification"] = data["qualification"].model_copy(
        update={"content_hash": data["qualification"].expected_content_hash()}
    )
    data["evaluated_at"] += timedelta(seconds=1, microseconds=offset)
    assert (evaluate_decision_readiness(**data).status == "READY_FOR_RECONSTRUCTION") is allowed


def test_scheduled_shadow_cost_permission_never_becomes_investment_decision_permission():
    data = complete()
    data["scope"] = data["scope"].model_copy(update={"scheduled_shadow": True})
    result = evaluate_decision_readiness(**data)
    assert "SCHEDULED_SHADOW_CANNOT_CREATE_INVESTMENT_DECISION" in result.blockers
    assert result.decision_id is None


@pytest.mark.parametrize(
    "action,allowed", [(Action.ADD, False), (Action.REDUCE, True), (Action.EXIT, True)]
)
def test_veto_blocks_increase_without_disabling_explicit_risk_reduction(action, allowed):
    data = complete()
    data["numeric"] = data["numeric"].model_copy(update={"risk_gate": "VETO"})
    data["action"] = action
    assert (evaluate_decision_readiness(**data).status == "READY_FOR_RECONSTRUCTION") is allowed


def test_nonpass_approved_investment_rule_blocks_add_and_never_uses_positive_model_stance():
    data = complete()
    facts = data["qualification"].facts
    data["qualification"] = data["qualification"].model_copy(
        update={"facts": (facts[0].model_copy(update={"value": "0"}), *facts[1:])}
    )
    data["qualification"] = data["qualification"].model_copy(
        update={"content_hash": data["qualification"].expected_content_hash()}
    )
    result = evaluate_decision_readiness(**data)
    assert "DECISION_GATE_NOT_PASSED:INVESTMENT_QUALITY" in result.blockers
    data["action"] = Action.REDUCE
    assert evaluate_decision_readiness(**data).status == "READY_FOR_RECONSTRUCTION"


def test_incomplete_strategy_rules_or_approximate_thresholds_are_not_accepted():
    payload = complete()["strategy"].rules.model_dump(mode="json")
    del payload["gates"]["TIMING"]
    with pytest.raises(ValidationError):
        StrategyDecisionRules.model_validate(payload)
    with pytest.raises(ValidationError):
        DecisionGateRule(metric="TIMING", comparison="GTE", threshold=0.1)
