"""Pure portfolio positions and conservative capacity calculations for PR-06."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.policy import PositionPolicy
from investment_os.domain.values import PositionBuckets, UtcTimestamp, Weight, exact_decimal


def _nonnegative(value: Decimal | int | str, field: str) -> Decimal:
    normalized = exact_decimal(value)
    if normalized < 0:
        raise DomainError(DomainErrorCode.OUT_OF_RANGE, f"{field} must not be negative")
    return normalized


@dataclass(frozen=True, slots=True)
class PortfolioPosition:
    """One instrument position with Core and Tactical quantities kept distinct."""

    instrument_id: UUID
    buckets: PositionBuckets
    average_cost: Decimal
    realized_pnl: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "average_cost", _nonnegative(self.average_cost, "average cost"))
        object.__setattr__(self, "realized_pnl", exact_decimal(self.realized_pnl))


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    """An immutable, synthetic-or-authorized as-of portfolio view."""

    portfolio_id: UUID
    as_of: UtcTimestamp
    cash: Decimal
    nav: Decimal
    positions: tuple[PortfolioPosition, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "cash", _nonnegative(self.cash, "cash"))
        object.__setattr__(self, "nav", _nonnegative(self.nav, "NAV"))
        if self.nav == 0:
            raise DomainError(DomainErrorCode.INVARIANT_VIOLATION, "NAV must be positive")
        instrument_ids = tuple(position.instrument_id for position in self.positions)
        if len(set(instrument_ids)) != len(instrument_ids):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "a portfolio snapshot must not repeat an instrument position",
            )


@dataclass(frozen=True, slots=True)
class PortfolioCapacityInputs:
    """Deterministic current and pre-approved pending exposure for one proposed increase."""

    instrument_weight: Weight
    sector_weight: Weight
    gross_exposure: Weight
    pending_instrument_weight: Weight
    pending_sector_weight: Weight
    pending_gross_exposure: Weight
    risk_budget_capacity: Weight
    liquidity_capacity: Weight


@dataclass(frozen=True, slots=True)
class CapacityLimit:
    code: str
    available: Weight


@dataclass(frozen=True, slots=True)
class PortfolioCapacity:
    """Fail-closed capacity result; pending approvals reserve capacity before a new increase."""

    requested_increase: Weight
    allowed_increase: Weight
    limits: tuple[CapacityLimit, ...]

    @property
    def has_requested_capacity(self) -> bool:
        return self.allowed_increase.value == self.requested_increase.value


def _headroom(limit: Weight, current: Weight, pending: Weight) -> Weight:
    return Weight(max(Decimal("0"), limit.value - current.value - pending.value))


def evaluate_portfolio_capacity(
    policy: PositionPolicy,
    inputs: PortfolioCapacityInputs,
    requested_increase: Weight,
) -> PortfolioCapacity:
    """Apply hard position, sector, gross, and minimum-cash limits without policy mutation."""

    limits = (
        CapacityLimit(
            "SINGLE_INSTRUMENT_CAP",
            _headroom(
                policy.single_instrument_max,
                inputs.instrument_weight,
                inputs.pending_instrument_weight,
            ),
        ),
        CapacityLimit(
            "SECTOR_CAP",
            _headroom(policy.sector_max, inputs.sector_weight, inputs.pending_sector_weight),
        ),
        CapacityLimit(
            "GROSS_EXPOSURE_CAP",
            _headroom(
                policy.gross_exposure_max,
                inputs.gross_exposure,
                inputs.pending_gross_exposure,
            ),
        ),
        CapacityLimit(
            "MINIMUM_CASH_CAP",
            _headroom(
                Weight(Decimal("1") - policy.minimum_cash.value),
                inputs.gross_exposure,
                inputs.pending_gross_exposure,
            ),
        ),
        CapacityLimit("RISK_BUDGET_CAP", inputs.risk_budget_capacity),
        CapacityLimit("LIQUIDITY_CAP", inputs.liquidity_capacity),
    )
    allowed = min((limit.available.value for limit in limits), default=Decimal("0"))
    return PortfolioCapacity(
        requested_increase=requested_increase,
        allowed_increase=Weight(min(requested_increase.value, allowed)),
        limits=limits,
    )
