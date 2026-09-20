"""V1 execution safety adapter: live orders are categorically disabled."""

from dataclasses import dataclass
from uuid import UUID

from investment_os.domain.enums import Action
from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.values import Quantity, UtcTimestamp


@dataclass(frozen=True, slots=True)
class LiveExecutionRequest:
    """A typed request shape retained solely so disabled live paths fail audibly."""

    decision_id: UUID
    approval_id: UUID
    instrument_id: UUID
    action: Action
    quantity: Quantity
    requested_at: UtcTimestamp

    def __post_init__(self) -> None:
        if self.action not in {Action.BUY, Action.ADD, Action.REDUCE, Action.EXIT}:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "only executable Decision actions may form an execution request",
            )
        if self.quantity.value == 0:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "execution request quantity must be positive",
            )


class DisabledLiveExecutionAdapter:
    """The only V1 live adapter; it cannot submit an order under any condition."""

    async def submit(self, request: LiveExecutionRequest) -> None:
        del request
        raise DomainError(
            DomainErrorCode.LIVE_EXECUTION_DISABLED,
            "live execution is disabled in V1; record only paper or manual execution",
        )
