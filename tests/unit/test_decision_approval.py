"""Human Decision approval TTL and V1 live-execution safety tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from investment_os.domain.approval import DecisionApproval, DecisionApprovalHistory
from investment_os.domain.enums import Action, ApprovalAction
from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.values import Quantity, UtcTimestamp
from investment_os.infrastructure.execution import (
    DisabledLiveExecutionAdapter,
    LiveExecutionRequest,
)

NOW = UtcTimestamp(datetime(2026, 9, 20, tzinfo=UTC))


def _approval(
    action: ApprovalAction = ApprovalAction.APPROVE,
    *,
    occurred_at: UtcTimestamp = NOW,
    decision_id: UUID | None = None,
) -> DecisionApproval:
    return DecisionApproval(
        decision_id=decision_id if decision_id is not None else uuid4(),
        actor_id="synthetic-owner",
        action=action,
        occurred_at=occurred_at,
        expires_at=(
            UtcTimestamp(occurred_at.value + timedelta(hours=24))
            if action is ApprovalAction.APPROVE
            else None
        ),
        comment="Synthetic audit record.",
    )


def test_approval_is_valid_before_expiry_and_invalid_at_exact_expiry() -> None:
    approval = _approval()

    assert approval.is_valid_at(UtcTimestamp(NOW.value + timedelta(hours=23, minutes=59)))
    assert not approval.is_valid_at(UtcTimestamp(NOW.value + timedelta(hours=24)))


def test_reject_or_revoke_supersedes_prior_approval() -> None:
    decision_id = uuid4()
    approval = _approval(decision_id=decision_id)
    revoked_at = UtcTimestamp(NOW.value + timedelta(hours=1))
    revoke = _approval(ApprovalAction.REVOKE, occurred_at=revoked_at, decision_id=decision_id)
    history = DecisionApprovalHistory(decision_id=decision_id, records=(approval, revoke))

    assert history.active_approval_at(UtcTimestamp(NOW.value + timedelta(minutes=30))) == approval
    assert history.active_approval_at(revoked_at) is None
    assert not _approval(ApprovalAction.REJECT).is_valid_at(NOW)


def test_approval_rejects_invalid_audit_records() -> None:
    with pytest.raises(DomainError, match="requires an expiry") as caught:
        DecisionApproval(
            decision_id=uuid4(),
            actor_id="synthetic-owner",
            action=ApprovalAction.APPROVE,
            occurred_at=NOW,
        )
    assert caught.value.code is DomainErrorCode.APPROVAL_INVALID

    with pytest.raises(DomainError, match="blank"):
        DecisionApproval(
            decision_id=uuid4(),
            actor_id=" ",
            action=ApprovalAction.REJECT,
            occurred_at=NOW,
        )


async def test_disabled_live_adapter_rejects_order_even_with_typed_approval() -> None:
    request = LiveExecutionRequest(
        decision_id=uuid4(),
        approval_id=uuid4(),
        instrument_id=uuid4(),
        action=Action.BUY,
        quantity=Quantity(Decimal("1")),
        requested_at=NOW,
    )

    with pytest.raises(DomainError) as caught:
        await DisabledLiveExecutionAdapter().submit(request)
    assert caught.value.code is DomainErrorCode.LIVE_EXECUTION_DISABLED
