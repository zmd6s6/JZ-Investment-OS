import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from investment_os.application.policy_schema import InvestmentPolicySchema
from investment_os.domain.enums import ActorType, PolicyStatus
from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.policy import PolicyVersion
from investment_os.domain.values import UtcTimestamp

POLICY_PATH = Path("config/investment-policy.test-default.json")


def policy_payload() -> dict[str, object]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def validate_payload(payload: dict[str, object]) -> InvestmentPolicySchema:
    return InvestmentPolicySchema.model_validate_json(json.dumps(payload))


def test_test_default_policy_round_trips_to_domain() -> None:
    schema = InvestmentPolicySchema.model_validate_json(POLICY_PATH.read_text(encoding="utf-8"))
    policy = schema.to_domain()
    assert policy.status is PolicyStatus.TEST_DEFAULT
    assert policy.position.single_instrument_max.value == Decimal("0.08")
    assert policy.position.gross_exposure_max.value == Decimal("1")
    assert policy.position.core_ratio_target.value == Decimal("0.75")
    assert policy.execution.auto_trade is False
    assert policy.execution.human_approval_required is True


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("position", "single_instrument_max_pct"), 26),
        (("position", "core_ratio_target"), 0.8),
        (("execution", "auto_trade"), True),
        (("execution", "human_approval_required"), False),
        (("entry", "require_risk_pass"), False),
    ],
)
def test_inconsistent_or_unsafe_policy_is_rejected(path: tuple[str, str], value: object) -> None:
    payload = policy_payload()
    section = payload[path[0]]
    assert isinstance(section, dict)
    section[path[1]] = value
    with pytest.raises(ValidationError):
        validate_payload(payload)


def test_unknown_policy_field_is_rejected() -> None:
    payload = policy_payload()
    payload["unreviewed_override"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        validate_payload(payload)


def test_holding_period_must_be_ordered() -> None:
    payload = policy_payload()
    horizon = payload["horizon"]
    assert isinstance(horizon, dict)
    core = horizon["core"]
    assert isinstance(core, dict)
    core["minimum_days"] = 100
    core["maximum_days"] = 99
    with pytest.raises(ValidationError, match="maximum_days"):
        validate_payload(payload)


def test_active_policy_version_requires_human_approval() -> None:
    schema = validate_payload(policy_payload())
    active_policy = replace(schema.to_domain(), status=PolicyStatus.ACTIVE)
    with pytest.raises(DomainError) as caught:
        PolicyVersion(
            id=uuid4(),
            version=1,
            policy=active_policy,
            created_at=UtcTimestamp(datetime.now(UTC)),
        )
    assert caught.value.code is DomainErrorCode.INVALID_POLICY


def test_active_policy_version_accepts_complete_human_approval() -> None:
    schema = validate_payload(policy_payload())
    active_policy = replace(schema.to_domain(), status=PolicyStatus.ACTIVE)
    approved_at = UtcTimestamp(datetime(2026, 9, 17, tzinfo=UTC))
    version = PolicyVersion(
        id=uuid4(),
        version=1,
        policy=active_policy,
        created_at=approved_at,
        effective_from=approved_at,
        approved_by="human-owner",
        approved_by_actor=ActorType.HUMAN,
        approved_at=approved_at,
    )
    assert version.policy.status is PolicyStatus.ACTIVE


def test_active_policy_rejects_non_human_approver() -> None:
    schema = validate_payload(policy_payload())
    active_policy = replace(schema.to_domain(), status=PolicyStatus.ACTIVE)
    approved_at = UtcTimestamp(datetime(2026, 9, 17, tzinfo=UTC))
    with pytest.raises(DomainError, match="must come from a human"):
        PolicyVersion(
            id=uuid4(),
            version=1,
            policy=active_policy,
            created_at=approved_at,
            effective_from=approved_at,
            approved_by="learning-engine",
            approved_by_actor=ActorType.LEARNING_ENGINE,
            approved_at=approved_at,
        )


def test_policy_version_must_be_positive() -> None:
    schema = validate_payload(policy_payload())
    with pytest.raises(DomainError, match="must be positive"):
        PolicyVersion(
            id=uuid4(),
            version=0,
            policy=schema.to_domain(),
            created_at=UtcTimestamp(datetime.now(UTC)),
        )
