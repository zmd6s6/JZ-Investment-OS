"""Strict JSON boundary for Investment Policy documents."""

from datetime import timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from investment_os.domain.enums import PolicyStatus, ReviewCadence, ThesisState
from investment_os.domain.policy import (
    BehaviorPolicy,
    EntryPolicy,
    ExecutionPolicy,
    ExitPolicy,
    HoldingPeriod,
    HorizonPolicy,
    InvestmentPolicy,
    PositionPolicy,
    ReviewFrequencyPolicy,
    StrategyPolicy,
)
from investment_os.domain.values import Weight

Percentage = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("100"))]
Ratio = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"))]
PositiveDays = Annotated[int, Field(gt=0)]
PositiveHours = Annotated[int, Field(gt=0)]


class StrictPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class PolicyMetadataSchema(StrictPolicyModel):
    name: Annotated[str, Field(min_length=1)]
    status: PolicyStatus


class StrategyPolicySchema(StrictPolicyModel):
    primary_style: Annotated[str, Field(min_length=1)]
    tactical_style: Annotated[str, Field(min_length=1)]


class HoldingPeriodSchema(StrictPolicyModel):
    minimum_days: PositiveDays
    maximum_days: PositiveDays

    @model_validator(mode="after")
    def maximum_must_follow_minimum(self) -> Self:
        if self.maximum_days < self.minimum_days:
            raise ValueError("maximum_days must be greater than or equal to minimum_days")
        return self

    def to_domain(self) -> HoldingPeriod:
        return HoldingPeriod(
            minimum=timedelta(days=self.minimum_days),
            maximum=timedelta(days=self.maximum_days),
        )


class HorizonPolicySchema(StrictPolicyModel):
    core: HoldingPeriodSchema
    tactical: HoldingPeriodSchema


class BehaviorPolicySchema(StrictPolicyModel):
    chase_high: bool
    frequent_trading: bool
    buy_only_because_price_fell: bool
    sell_only_because_position_is_profitable: bool
    average_down_without_thesis_check: bool
    reason_required_for_every_action: bool


class PositionPolicySchema(StrictPolicyModel):
    single_instrument_max_pct: Percentage
    sector_max_pct: Percentage
    gross_exposure_max_pct: Percentage
    minimum_cash_pct: Percentage
    core_ratio_target: Ratio
    tactical_ratio_target: Ratio

    @model_validator(mode="after")
    def validate_cross_field_limits(self) -> Self:
        if self.single_instrument_max_pct > self.sector_max_pct:
            raise ValueError("single_instrument_max_pct must not exceed sector_max_pct")
        if self.sector_max_pct > self.gross_exposure_max_pct:
            raise ValueError("sector_max_pct must not exceed gross_exposure_max_pct")
        if self.core_ratio_target + self.tactical_ratio_target != Decimal("1"):
            raise ValueError("Core and Tactical target ratios must sum exactly to one")
        return self


class EntryPolicySchema(StrictPolicyModel):
    require_thesis_states: frozenset[ThesisState]
    require_timing_confirmation: bool
    require_portfolio_capacity: bool
    require_risk_pass: bool

    @model_validator(mode="after")
    def validate_entry_gates(self) -> Self:
        if not self.require_thesis_states:
            raise ValueError("require_thesis_states must not be empty")
        if self.require_thesis_states - {ThesisState.VALID, ThesisState.STRENGTHENING}:
            raise ValueError("entry states may only contain VALID and STRENGTHENING")
        if not self.require_portfolio_capacity or not self.require_risk_pass:
            raise ValueError("portfolio capacity and Risk PASS are mandatory")
        return self


class ExitPolicySchema(StrictPolicyModel):
    thesis_broken: Literal["MANDATORY_REVIEW"]
    hard_risk_veto: Literal["NO_NEW_OR_ADDITIONAL_EXPOSURE"]


class ExecutionPolicySchema(StrictPolicyModel):
    auto_trade: Literal[False]
    human_approval_required: Literal[True]
    approval_ttl_hours: PositiveHours


class ReviewFrequencySchema(StrictPolicyModel):
    holdings: ReviewCadence
    watchlist: ReviewCadence
    screening: ReviewCadence
    portfolio: ReviewCadence
    strategy: ReviewCadence


class InvestmentPolicySchema(StrictPolicyModel):
    """Versioned machine protocol for an Investment Policy configuration."""

    schema_version: Literal["1.0"]
    metadata: PolicyMetadataSchema
    strategy: StrategyPolicySchema
    horizon: HorizonPolicySchema
    behavior: BehaviorPolicySchema
    position: PositionPolicySchema
    entry: EntryPolicySchema
    exit: ExitPolicySchema
    execution: ExecutionPolicySchema
    review_frequency: ReviewFrequencySchema

    def to_domain(self) -> InvestmentPolicy:
        hundred = Decimal("100")
        return InvestmentPolicy(
            name=self.metadata.name,
            status=self.metadata.status,
            strategy=StrategyPolicy(
                primary_style=self.strategy.primary_style,
                tactical_style=self.strategy.tactical_style,
            ),
            horizon=HorizonPolicy(
                core=self.horizon.core.to_domain(),
                tactical=self.horizon.tactical.to_domain(),
            ),
            behavior=BehaviorPolicy(**self.behavior.model_dump()),
            position=PositionPolicy(
                single_instrument_max=Weight(self.position.single_instrument_max_pct / hundred),
                sector_max=Weight(self.position.sector_max_pct / hundred),
                gross_exposure_max=Weight(self.position.gross_exposure_max_pct / hundred),
                minimum_cash=Weight(self.position.minimum_cash_pct / hundred),
                core_ratio_target=Weight(self.position.core_ratio_target),
                tactical_ratio_target=Weight(self.position.tactical_ratio_target),
            ),
            entry=EntryPolicy(
                require_thesis_states=self.entry.require_thesis_states,
                require_timing_confirmation=self.entry.require_timing_confirmation,
                require_portfolio_capacity=self.entry.require_portfolio_capacity,
                require_risk_pass=self.entry.require_risk_pass,
            ),
            exit=ExitPolicy(
                thesis_broken=self.exit.thesis_broken,
                hard_risk_veto=self.exit.hard_risk_veto,
            ),
            execution=ExecutionPolicy(
                auto_trade=self.execution.auto_trade,
                human_approval_required=self.execution.human_approval_required,
                approval_ttl=timedelta(hours=self.execution.approval_ttl_hours),
            ),
            review_frequency=ReviewFrequencyPolicy(**self.review_frequency.model_dump()),
        )
