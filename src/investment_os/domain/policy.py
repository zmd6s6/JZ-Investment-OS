"""Versioned Investment Policy domain objects and cross-field invariants."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from investment_os.domain.enums import ActorType, PolicyStatus, ReviewCadence, ThesisState
from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.values import UtcTimestamp, Weight


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DomainError(DomainErrorCode.INVALID_POLICY, message)


@dataclass(frozen=True, slots=True)
class StrategyPolicy:
    primary_style: str
    tactical_style: str

    def __post_init__(self) -> None:
        _require(bool(self.primary_style.strip()), "primary strategy style is required")
        _require(bool(self.tactical_style.strip()), "tactical strategy style is required")


@dataclass(frozen=True, slots=True)
class HoldingPeriod:
    minimum: timedelta
    maximum: timedelta

    def __post_init__(self) -> None:
        _require(self.minimum > timedelta(0), "minimum holding period must be positive")
        _require(self.maximum >= self.minimum, "maximum holding period must not precede minimum")


@dataclass(frozen=True, slots=True)
class HorizonPolicy:
    core: HoldingPeriod
    tactical: HoldingPeriod


@dataclass(frozen=True, slots=True)
class BehaviorPolicy:
    chase_high: bool
    frequent_trading: bool
    buy_only_because_price_fell: bool
    sell_only_because_position_is_profitable: bool
    average_down_without_thesis_check: bool
    reason_required_for_every_action: bool

    def __post_init__(self) -> None:
        _require(self.reason_required_for_every_action, "every action must require a reason")


@dataclass(frozen=True, slots=True)
class PositionPolicy:
    single_instrument_max: Weight
    sector_max: Weight
    gross_exposure_max: Weight
    minimum_cash: Weight
    core_ratio_target: Weight
    tactical_ratio_target: Weight

    def __post_init__(self) -> None:
        _require(
            self.single_instrument_max.value <= self.sector_max.value,
            "single-instrument maximum must not exceed sector maximum",
        )
        _require(
            self.sector_max.value <= self.gross_exposure_max.value,
            "sector maximum must not exceed gross exposure maximum",
        )
        _require(
            self.core_ratio_target.value + self.tactical_ratio_target.value == 1,
            "Core and Tactical target ratios must sum exactly to one",
        )


@dataclass(frozen=True, slots=True)
class EntryPolicy:
    require_thesis_states: frozenset[ThesisState]
    require_timing_confirmation: bool
    require_portfolio_capacity: bool
    require_risk_pass: bool

    def __post_init__(self) -> None:
        _require(bool(self.require_thesis_states), "at least one entry thesis state is required")
        _require(
            not self.require_thesis_states.difference(
                {ThesisState.VALID, ThesisState.STRENGTHENING}
            ),
            "entry thesis states may only be VALID or STRENGTHENING",
        )
        _require(self.require_risk_pass, "entry must require Risk PASS")
        _require(self.require_portfolio_capacity, "entry must require portfolio capacity")


@dataclass(frozen=True, slots=True)
class ExitPolicy:
    thesis_broken: str
    hard_risk_veto: str

    def __post_init__(self) -> None:
        _require(self.thesis_broken == "MANDATORY_REVIEW", "BROKEN thesis must mandate review")
        _require(
            self.hard_risk_veto == "NO_NEW_OR_ADDITIONAL_EXPOSURE",
            "hard Risk Veto must prohibit new or additional exposure",
        )


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    auto_trade: bool
    human_approval_required: bool
    approval_ttl: timedelta

    def __post_init__(self) -> None:
        _require(not self.auto_trade, "auto_trade must remain false in V1")
        _require(self.human_approval_required, "human approval is mandatory in V1")
        _require(self.approval_ttl > timedelta(0), "approval TTL must be positive")


@dataclass(frozen=True, slots=True)
class ReviewFrequencyPolicy:
    holdings: ReviewCadence
    watchlist: ReviewCadence
    screening: ReviewCadence
    portfolio: ReviewCadence
    strategy: ReviewCadence


@dataclass(frozen=True, slots=True)
class InvestmentPolicy:
    name: str
    status: PolicyStatus
    strategy: StrategyPolicy
    horizon: HorizonPolicy
    behavior: BehaviorPolicy
    position: PositionPolicy
    entry: EntryPolicy
    exit: ExitPolicy
    execution: ExecutionPolicy
    review_frequency: ReviewFrequencyPolicy

    def __post_init__(self) -> None:
        _require(bool(self.name.strip()), "policy name is required")


@dataclass(frozen=True, slots=True)
class PolicyVersion:
    """Immutable policy snapshot; ACTIVE versions require explicit human approval."""

    id: UUID
    version: int
    policy: InvestmentPolicy
    created_at: UtcTimestamp
    effective_from: UtcTimestamp | None = None
    approved_by: str | None = None
    approved_by_actor: ActorType | None = None
    approved_at: UtcTimestamp | None = None

    def __post_init__(self) -> None:
        _require(self.version > 0, "policy version must be positive")
        if self.policy.status is PolicyStatus.ACTIVE:
            _require(
                bool(self.approved_by and self.approved_by.strip()), "ACTIVE policy needs approver"
            )
            _require(
                self.approved_by_actor is ActorType.HUMAN,
                "ACTIVE policy approval must come from a human",
            )
            _require(self.approved_at is not None, "ACTIVE policy needs approval time")
            _require(self.effective_from is not None, "ACTIVE policy needs effective time")
            if self.approved_at is not None and self.effective_from is not None:
                _require(
                    self.effective_from.value >= self.approved_at.value,
                    "policy cannot become effective before approval",
                )
