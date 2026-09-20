"""Immutable paper/manual execution records; V1 has no live execution mode."""

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID, uuid4

from investment_os.domain.approval import DecisionApproval
from investment_os.domain.enums import ExecutionMode, ExecutionStatus
from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.values import Quantity, UtcTimestamp, exact_decimal


def _reference(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise DomainError(
            DomainErrorCode.INVARIANT_VIOLATION,
            "execution reference must not be blank",
        )
    return normalized


@dataclass(frozen=True, slots=True)
class DecisionExecution:
    """A non-live execution receipt linked to an unexpired, named human approval."""

    decision_id: UUID
    approval: DecisionApproval
    mode: ExecutionMode
    status: ExecutionStatus
    requested_quantity: Quantity
    filled_quantity: Quantity
    recorded_at: UtcTimestamp
    average_price: Decimal | int | str | None = None
    external_references: tuple[str, ...] = ()
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.approval.decision_id != self.decision_id:
            raise DomainError(
                DomainErrorCode.APPROVAL_INVALID,
                "execution approval must belong to the same Decision",
            )
        if not self.approval.is_valid_at(self.recorded_at):
            raise DomainError(
                DomainErrorCode.APPROVAL_INVALID,
                "paper or manual execution requires a current human approval",
            )
        if self.filled_quantity.value > self.requested_quantity.value:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "filled execution quantity cannot exceed the requested quantity",
            )
        normalized_price = (
            exact_decimal(self.average_price) if self.average_price is not None else None
        )
        if normalized_price is not None and normalized_price <= 0:
            raise DomainError(
                DomainErrorCode.OUT_OF_RANGE,
                "execution average price must be positive",
            )
        object.__setattr__(self, "average_price", normalized_price)
        object.__setattr__(
            self,
            "external_references",
            tuple(_reference(reference) for reference in self.external_references),
        )
        _validate_fill_state(
            self.status,
            self.requested_quantity,
            self.filled_quantity,
            normalized_price,
        )
        if self.mode is ExecutionMode.MANUAL and not self.external_references:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "manual execution requires a sanitized external reference",
            )

    @property
    def approval_id(self) -> UUID:
        return self.approval.id


def _validate_fill_state(
    status: ExecutionStatus,
    requested: Quantity,
    filled: Quantity,
    average_price: Decimal | None,
) -> None:
    if status is ExecutionStatus.PENDING:
        valid = filled.value == 0 and average_price is None
    elif status is ExecutionStatus.PARTIAL:
        valid = 0 < filled.value < requested.value and average_price is not None
    elif status is ExecutionStatus.FILLED:
        valid = filled.value == requested.value and average_price is not None
    else:
        valid = filled.value < requested.value
    if not valid:
        raise DomainError(
            DomainErrorCode.INVARIANT_VIOLATION,
            f"execution status {status.value} is inconsistent with its fill quantities",
        )
