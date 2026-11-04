"""Versioned frozen numeric sources and risk/sizing artifacts for shadow analysis."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from investment_os.application.portfolio_valuation import FrozenPortfolio, fingerprint
from investment_os.domain.enums import PositionBucket, RiskIntent
from investment_os.domain.errors import DomainError
from investment_os.domain.sizing import SizingFormula
from investment_os.domain.values import Weight, exact_decimal


def exact_number(value: object) -> Decimal:
    if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool):
        raise ValueError("finite exact decimal string or integer required")
    try:
        return exact_decimal(value)
    except DomainError:
        raise ValueError("finite exact decimal required") from None


class NumericDto(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SizingRules(NumericDto):
    schema_version: Literal["sizing-rules-1.0"] = "sizing-rules-1.0"
    formula_version: str = Field(min_length=1, max_length=64)
    intent_weights: dict[RiskIntent, Decimal]
    target_volatility: Decimal
    volatility_floor: Decimal
    volatility_scale_min: Decimal
    volatility_scale_max: Decimal
    reduce_fraction: Decimal
    max_instrument_volatility: Decimal
    correlation_attention_threshold: Decimal

    @field_validator(
        "target_volatility",
        "volatility_floor",
        "volatility_scale_min",
        "volatility_scale_max",
        "reduce_fraction",
        "max_instrument_volatility",
        "correlation_attention_threshold",
        mode="before",
    )
    @classmethod
    def exact(cls, value: object) -> Decimal:
        return exact_number(value)

    @field_validator("intent_weights", mode="before")
    @classmethod
    def exact_weights(cls, value: object) -> object:
        if not isinstance(value, dict):
            raise ValueError("explicit complete intent map required")
        return {key: exact_number(number) for key, number in value.items()}

    @model_validator(mode="after")
    def governed_complete_formula(self) -> Self:
        self.to_formula()
        if any(self.intent_weights[intent] != 0 for intent in (RiskIntent.NONE, RiskIntent.EXIT)):
            raise ValueError("NONE and EXIT intents cannot request exposure")
        if (
            self.max_instrument_volatility <= 0
            or not -1 <= self.correlation_attention_threshold <= 1
        ):
            raise ValueError("explicit volatility and correlation attention rules required")
        return self

    def to_formula(self) -> SizingFormula:
        return SizingFormula(
            self.formula_version,
            {key: Weight(value) for key, value in self.intent_weights.items()},
            self.target_volatility,
            self.volatility_floor,
            self.volatility_scale_min,
            self.volatility_scale_max,
            Weight(self.reduce_fraction),
        )


class NumericFact(NumericDto):
    metric: Literal[
        "REFERENCE_PRICE", "VOLATILITY", "LIQUIDITY_CAPACITY", "RISK_BUDGET_CAPACITY", "CORRELATION"
    ]
    instrument_id: UUID
    evidence_id: UUID
    value: Decimal
    currency: str | None = None

    @field_validator("value", mode="before")
    @classmethod
    def exact(cls, value: object) -> Decimal:
        return exact_number(value)


class NumericTarget(NumericDto):
    instrument_id: UUID
    currency: str
    sector: str = Field(min_length=1)
    lot_size: Decimal

    @field_validator("lot_size", mode="before")
    @classmethod
    def exact_positive(cls, value: object) -> Decimal:
        number = exact_number(value)
        if number <= 0:
            raise ValueError("lot size must be positive")
        return number


class NumericSourceSnapshot(NumericDto):
    schema_version: Literal["analysis-numeric-input-1.0"] = "analysis-numeric-input-1.0"
    snapshot_id: UUID
    portfolio_id: UUID
    instrument_id: UUID
    policy_version_id: UUID
    portfolio_identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target: NumericTarget
    source_kind: Literal["REFERENCE_ONLY", "SYNTHETIC_FIXTURE"]
    source_name: str = Field(min_length=1, max_length=255)
    created_at: AwareDatetime
    as_of: AwareDatetime
    expires_at: AwareDatetime
    facts: tuple[NumericFact, ...] = Field(min_length=1, max_length=1100)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    simulation_only: Literal[True] = True

    @model_validator(mode="after")
    def unique_facts_and_times(self) -> Self:
        if self.expires_at <= self.as_of:
            raise ValueError("numeric source expiry must follow its as-of")
        keys = [(fact.metric, fact.instrument_id) for fact in self.facts]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate numeric facts cannot silently override")
        return self


def portfolio_identity(book: FrozenPortfolio) -> str:
    return fingerprint(book.model_dump(mode="json", exclude={"captured_at"}))


def frozen_ledger_fingerprint(book: FrozenPortfolio) -> str:
    """Same cash/position identity used by human approval, over the frozen P5 capture."""
    return fingerprint(
        {
            "portfolio_id": str(book.portfolio_id),
            "cash": str(book.cash),
            "positions": [
                {
                    "id": str(holding.position_id),
                    "version": holding.version,
                    "core": str(holding.core_quantity),
                    "tactical": str(holding.tactical_quantity),
                }
                for holding in sorted(book.holdings, key=lambda holding: str(holding.position_id))
            ],
        }
    )


class NumericSourcePort(Protocol):
    async def get(self, snapshot_id: UUID) -> NumericSourceSnapshot: ...
    async def list(
        self, portfolio_id: UUID, instrument_id: UUID
    ) -> tuple[NumericSourceSnapshot, ...]: ...


class RiskSizingView(NumericDto):
    schema_version: Literal["analysis-risk-sizing-1.0"] = "analysis-risk-sizing-1.0"
    risk_assessment_id: UUID | None = None
    sizing_run_id: UUID | None = None
    numeric_snapshot_id: UUID | None = None
    risk_gate: Literal["UNKNOWN", "PASS", "VETO"] = "UNKNOWN"
    sizing_status: Literal["BLOCKED", "COMPUTED"] = "BLOCKED"
    policy_version_id: UUID | None = None
    bucket: PositionBucket | None = None
    target_quantity: Decimal | None = None
    delta_quantity: Decimal | None = None
    blockers: tuple[str, ...] = ()
    risk_flags: tuple[dict[str, object], ...] = ()
    numbers: dict[str, object] = Field(default_factory=dict)
    sizing_input: dict[str, object] | None = None
    sizing_output: dict[str, object] | None = None
    evaluated_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    simulation_only: Literal[True] = True
    execution_allowed: Literal[False] = False
    auto_trade: Literal[False] = False


def utc_now() -> datetime:
    return datetime.now(UTC)
