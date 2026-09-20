"""S10 approval lifecycle facts are derived from immutable human actions only."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from investment_os.application.approval_gate import approval_transition_context
from investment_os.domain.approval import DecisionApproval, DecisionApprovalHistory
from investment_os.domain.enums import Action, ApprovalAction, DecisionState
from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.state_machines import transition_decision
from investment_os.domain.values import UtcTimestamp

NOW = UtcTimestamp(datetime(2026, 9, 20, tzinfo=UTC))


def _record(
    action: ApprovalAction,
    *,
    decision_id: UUID,
    occurred_at: UtcTimestamp = NOW,
    expires_at: UtcTimestamp | None = None,
) -> DecisionApproval:
    return DecisionApproval(
        decision_id=decision_id,
        actor_id="synthetic-owner",
        action=action,
        occurred_at=occurred_at,
        expires_at=(expires_at if action is ApprovalAction.APPROVE else None),
        comment="Synthetic human approval lifecycle action.",
    )


def _history(*records: DecisionApproval) -> DecisionApprovalHistory:
    return DecisionApprovalHistory(decision_id=records[0].decision_id, records=records)


def _transition(
    current: DecisionState,
    target: DecisionState,
    history: DecisionApprovalHistory | None,
    *,
    as_of: UtcTimestamp = NOW,
) -> None:
    transition_decision(
        current,
        target,
        approval_transition_context(
            action=Action.BUY,
            history=history,
            as_of=as_of,
            input_snapshot_matches=True,
            price_within_tolerance=True,
        ),
        reason_codes=("SYNTHETIC_APPROVAL_LIFECYCLE",),
        occurred_at=as_of,
    )


def test_s10_approval_paths_require_the_matching_immutable_human_record() -> None:
    decision_id = uuid4()
    approval = _record(
        ApprovalAction.APPROVE,
        decision_id=decision_id,
        expires_at=UtcTimestamp(NOW.value + timedelta(hours=1)),
    )
    _transition(DecisionState.PENDING_APPROVAL, DecisionState.APPROVED, _history(approval))

    rejected = _record(ApprovalAction.REJECT, decision_id=uuid4())
    _transition(DecisionState.PENDING_APPROVAL, DecisionState.REJECTED, _history(rejected))

    expired = _record(
        ApprovalAction.APPROVE,
        decision_id=uuid4(),
        expires_at=UtcTimestamp(NOW.value + timedelta(minutes=1)),
    )
    _transition(
        DecisionState.PENDING_APPROVAL,
        DecisionState.EXPIRED,
        _history(expired),
        as_of=UtcTimestamp(NOW.value + timedelta(minutes=1)),
    )


def test_s10_no_approval_rejection_or_expiry_cannot_be_invented() -> None:
    with pytest.raises(DomainError) as approved:
        _transition(DecisionState.PENDING_APPROVAL, DecisionState.APPROVED, None)
    assert approved.value.code is DomainErrorCode.APPROVAL_INVALID

    with pytest.raises(DomainError) as rejected:
        _transition(DecisionState.PENDING_APPROVAL, DecisionState.REJECTED, None)
    assert rejected.value.code is DomainErrorCode.APPROVAL_INVALID

    with pytest.raises(DomainError) as expired:
        _transition(DecisionState.PENDING_APPROVAL, DecisionState.EXPIRED, None)
    assert expired.value.code is DomainErrorCode.APPROVAL_INVALID


def test_s10_revoke_or_expiry_blocks_execution_and_revocation_cancels() -> None:
    decision_id = uuid4()
    approval = _record(
        ApprovalAction.APPROVE,
        decision_id=decision_id,
        expires_at=UtcTimestamp(NOW.value + timedelta(hours=1)),
    )
    revoke_at = UtcTimestamp(NOW.value + timedelta(minutes=10))
    revoked = _record(ApprovalAction.REVOKE, decision_id=decision_id, occurred_at=revoke_at)
    history = _history(approval, revoked)

    _transition(DecisionState.APPROVED, DecisionState.CANCELLED, history, as_of=revoke_at)
    with pytest.raises(DomainError) as blocked:
        _transition(
            DecisionState.APPROVED, DecisionState.EXECUTION_PENDING, history, as_of=revoke_at
        )
    assert blocked.value.code is DomainErrorCode.APPROVAL_INVALID
