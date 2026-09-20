"""Evidence-first Risk Veto tests for the PR-06 domain slice."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from investment_os.domain.enums import Action, RiskGateState
from investment_os.domain.errors import DomainError
from investment_os.domain.risk import (
    RiskAssessment,
    RiskFlag,
    RiskFlagKind,
    RiskSeverity,
)
from investment_os.domain.values import UtcTimestamp

NOW = UtcTimestamp(datetime(2026, 9, 20, tzinfo=UTC))


def _assessment(*flags: RiskFlag) -> RiskAssessment:
    return RiskAssessment(
        id=uuid4(),
        version=1,
        as_of=NOW,
        expires_at=UtcTimestamp(NOW.value + timedelta(days=1)),
        flags=flags,
    )


def test_hard_risk_flag_vetoes_buy_and_add_but_not_reduce_or_exit() -> None:
    assessment = _assessment(
        RiskFlag(
            code="SYNTHETIC_AUDIT_ANOMALY",
            kind=RiskFlagKind.HARD,
            severity=RiskSeverity.CRITICAL,
            evidence_ids=(uuid4(),),
            release_condition="A synthetic independent audit clears the anomaly.",
        )
    )

    assert assessment.gate is RiskGateState.VETO
    assert not assessment.permits_action(Action.BUY)
    assert not assessment.permits_action(Action.ADD)
    assert assessment.permits_action(Action.REDUCE)
    assert assessment.permits_action(Action.EXIT)


def test_soft_flags_preserve_pass_with_evidence_and_release_conditions() -> None:
    evidence_id = uuid4()
    assessment = _assessment(
        RiskFlag(
            code="SYNTHETIC_VALUATION_RISK",
            kind=RiskFlagKind.SOFT,
            severity=RiskSeverity.MEDIUM,
            evidence_ids=(evidence_id,),
            release_condition="Synthetic valuation returns to its monitored range.",
        )
    )

    assert assessment.gate is RiskGateState.PASS
    assert assessment.permits_action(Action.BUY)
    assert assessment.evidence_ids == (evidence_id,)
    assert assessment.is_active_at(NOW)
    assert not assessment.is_active_at(UtcTimestamp(NOW.value + timedelta(days=1)))
    assert (
        assessment.content_hash
        == _assessment(
            RiskFlag(
                code="SYNTHETIC_VALUATION_RISK",
                kind=RiskFlagKind.SOFT,
                severity=RiskSeverity.MEDIUM,
                evidence_ids=(evidence_id,),
                release_condition="Synthetic valuation returns to its monitored range.",
            )
        ).content_hash
    )


def test_risk_assessment_rejects_unauditable_flags_and_expired_versions() -> None:
    with pytest.raises(DomainError, match="requires unique Evidence"):
        RiskFlag(
            code="SYNTHETIC_UNKNOWN_SOURCE",
            kind=RiskFlagKind.HARD,
            severity=RiskSeverity.HIGH,
            evidence_ids=(),
            release_condition="Synthetic source provenance is established.",
        )
    with pytest.raises(DomainError, match="expiry must follow"):
        RiskAssessment(
            id=uuid4(),
            version=1,
            as_of=NOW,
            expires_at=NOW,
            flags=(),
        )
