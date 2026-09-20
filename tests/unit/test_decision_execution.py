"""Paper/manual execution records cannot bypass approval or fill-accounting invariants."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from investment_os.domain.approval import DecisionApproval
from investment_os.domain.enums import ApprovalAction, ExecutionMode, ExecutionStatus
from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.execution import DecisionExecution
from investment_os.domain.values import Quantity, UtcTimestamp

NOW = UtcTimestamp(datetime(2026, 9, 20, tzinfo=UTC))


def _approval(
    *, decision_id: UUID | None = None, expires_at: UtcTimestamp | None = None
) -> DecisionApproval:
    return DecisionApproval(
        decision_id=decision_id if decision_id is not None else uuid4(),
        actor_id="synthetic-owner",
        action=ApprovalAction.APPROVE,
        occurred_at=NOW,
        expires_at=expires_at or UtcTimestamp(NOW.value + timedelta(hours=24)),
        comment="Synthetic approval for non-live execution.",
    )


def _execution(**overrides: object) -> DecisionExecution:
    approval = _approval()
    values: dict[str, object] = {
        "decision_id": approval.decision_id,
        "approval": approval,
        "mode": ExecutionMode.PAPER,
        "status": ExecutionStatus.FILLED,
        "requested_quantity": Quantity(Decimal("4")),
        "filled_quantity": Quantity(Decimal("4")),
        "recorded_at": NOW,
        "average_price": Decimal("12.50"),
    }
    values.update(overrides)
    return DecisionExecution(**values)  # type: ignore[arg-type]


def test_paper_execution_is_immutable_and_linked_to_current_human_approval() -> None:
    execution = _execution()

    assert execution.mode is ExecutionMode.PAPER
    assert execution.approval_id == execution.approval.id
    assert execution.average_price == Decimal("12.50")


def test_manual_partial_execution_requires_audit_reference() -> None:
    execution = _execution(
        mode=ExecutionMode.MANUAL,
        status=ExecutionStatus.PARTIAL,
        requested_quantity=Quantity(Decimal("4")),
        filled_quantity=Quantity(Decimal("1")),
        external_references=("synthetic-manual-trade-reference",),
    )

    assert execution.status is ExecutionStatus.PARTIAL
    assert execution.external_references == ("synthetic-manual-trade-reference",)


def test_execution_rejects_expired_mismatched_or_inconsistent_approval_and_fill() -> None:
    expired_approval = _approval(expires_at=UtcTimestamp(NOW.value + timedelta(minutes=1)))
    with pytest.raises(DomainError) as expired:
        _execution(
            approval=expired_approval,
            decision_id=expired_approval.decision_id,
            recorded_at=UtcTimestamp(NOW.value + timedelta(minutes=1)),
        )
    assert expired.value.code is DomainErrorCode.APPROVAL_INVALID

    with pytest.raises(DomainError, match="same Decision"):
        _execution(decision_id=uuid4())
    with pytest.raises(DomainError, match="inconsistent"):
        _execution(filled_quantity=Quantity(Decimal("1")))
    with pytest.raises(DomainError, match="manual execution requires"):
        _execution(mode=ExecutionMode.MANUAL)
