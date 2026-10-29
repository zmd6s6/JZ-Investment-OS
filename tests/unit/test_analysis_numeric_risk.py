"""Named deterministic numeric-risk and versioned-policy boundaries (synthetic only)."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from investment_os.application.analysis_risk_sizing import SizingRules
from investment_os.application.policy_schema import InvestmentPolicySchema
from investment_os.domain.enums import Action, RiskIntent, ThesisState
from investment_os.domain.risk_evaluation import RiskNumbers, evaluate_numeric_risk
from investment_os.domain.values import UtcTimestamp, Weight


def rules():
    return {
        "schema_version": "sizing-rules-1.0",
        "formula_version": "synthetic-205-v1",
        "intent_weights": {
            intent.value: "0" if intent in {RiskIntent.NONE, RiskIntent.EXIT} else "0.05"
            for intent in RiskIntent
        },
        "target_volatility": "0.20",
        "volatility_floor": "0.10",
        "volatility_scale_min": "0.5",
        "volatility_scale_max": "1",
        "reduce_fraction": "0.5",
        "max_instrument_volatility": "0.4",
        "correlation_attention_threshold": "0.8",
    }


def numbers():
    policy = (
        InvestmentPolicySchema.model_validate_json(
            Path("config/investment-policy.test-default.json").read_text(encoding="utf-8")
        )
        .to_domain()
        .position
    )
    return RiskNumbers(
        Weight("0.02"),
        Weight("0.1"),
        Weight("0.2"),
        Weight("0.8"),
        Weight(0),
        Weight(0),
        Weight(0),
        Decimal("0.2"),
        Weight("0.1"),
        Weight("0.1"),
        Decimal("0.3"),
        Decimal("0.8"),
        Decimal("0.4"),
        Weight("0.015"),
        Weight("0.005"),
        ThesisState.VALID,
        policy,
        (uuid4(),),
    )


def assess(value):
    at = datetime(2026, 10, 29, tzinfo=UTC)
    return evaluate_numeric_risk(
        value,
        identifier=uuid4(),
        as_of=UtcTimestamp(at),
        expires_at=UtcTimestamp(at + timedelta(hours=1)),
    )


def test_complete_numeric_risk_is_evidence_backed_deterministic_and_expiry_half_open():
    value = numbers()
    first, second = assess(value), assess(value)
    assert first.content_hash == second.content_hash
    assert first.gate.value == "PASS" and first.flags[0].code == "NUMERIC_LIMITS_EVALUATED"
    assert first.flags[0].evidence_ids == value.evidence_ids
    assert first.is_active_at(UtcTimestamp(first.expires_at.value - timedelta(microseconds=1)))
    assert not first.is_active_at(first.expires_at)


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("pending_instrument", Weight("0.1"), "SINGLE_INSTRUMENT_LIMIT"),
        ("pending_sector", Weight("0.3"), "SECTOR_CONCENTRATION_LIMIT"),
        ("pending_gross", Weight("0.9"), "GROSS_EXPOSURE_LIMIT"),
        ("cash_weight", Weight("0.01"), "MINIMUM_CASH_LIMIT"),
        ("liquidity_capacity", Weight(0), "LIQUIDITY_INSUFFICIENT"),
        ("thesis_state", ThesisState.BROKEN, "THESIS_BROKEN_NO_INCREASE"),
    ],
)
def test_hard_numeric_veto_never_permits_increase_but_preserves_risk_reduction(field, value, code):
    risk = assess(replace(numbers(), **{field: value}))
    assert code in {flag.code for flag in risk.flags}
    assert risk.gate.value == "VETO" and not risk.permits_action(Action.ADD)
    assert risk.permits_action(Action.REDUCE) and risk.permits_action(Action.EXIT)


def test_core_tactical_do_not_hide_exposure_or_accept_missing_evidence_and_binary_numbers():
    with pytest.raises(ValueError):
        replace(numbers(), core_weight=Weight("0.01"))
    with pytest.raises(ValueError):
        replace(numbers(), evidence_ids=())
    with pytest.raises(ValueError):
        SizingRules.model_validate({**rules(), "target_volatility": 0.2})
    with pytest.raises(ValidationError):
        SizingRules.model_validate(
            {key: value for key, value in rules().items() if key != "reduce_fraction"}
        )


def test_policy_10_preserved_and_no_formula_defaults_or_silent_sizing_upgrade():
    document = json.loads(
        Path("config/investment-policy.test-default.json").read_text(encoding="utf-8")
    )
    assert InvestmentPolicySchema.model_validate_json(json.dumps(document)).sizing is None
    document["sizing"] = rules()
    with pytest.raises(ValidationError):
        InvestmentPolicySchema.model_validate_json(json.dumps(document))
    document["schema_version"] = "1.1"
    validated = InvestmentPolicySchema.model_validate_json(json.dumps(document))
    assert validated.sizing.to_formula().version == "synthetic-205-v1"
    assert validated.metadata.status.value == "TEST_DEFAULT"  # parsing never activates a Policy.
