"""Immutable policy and runtime provenance; snapshots never confer investment authority."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from investment_os.application.analysis_models import digest
from investment_os.application.policy_schema import InvestmentPolicySchema
from investment_os.domain.agent import AgentRole, AgentTool
from investment_os.domain.enums import PolicyStatus, RiskIntent
from investment_os.domain.errors import DomainError
from investment_os.domain.sizing import SizingFormula
from investment_os.domain.values import Weight


class FrozenGovernanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def policy_config_hash(config: InvestmentPolicySchema) -> str:
    payload = config.model_dump(mode="json")
    # This field is a set, not a list whose incidental serialization order is meaningful.
    payload["entry"]["require_thesis_states"] = sorted(payload["entry"]["require_thesis_states"])
    return digest(payload)


class FrozenAnalysisPolicy(FrozenGovernanceModel):
    schema_version: Literal["1.0"] = "1.0"
    mode: Literal["ACTIVE", "TEST_DEFAULT"]
    policy_id: UUID | None = None
    policy_version_id: UUID | None = None
    version: int = Field(gt=0)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    config: InvestmentPolicySchema
    effective_from: datetime | None = None
    approved_by: str | None = None
    approved_by_actor: Literal["HUMAN"] | None = None
    approved_at: datetime | None = None

    @property
    def label(self) -> str:
        return (
            "TEST_DEFAULT"
            if self.mode == "TEST_DEFAULT"
            else f"{self.config.metadata.name}@{self.version}"
        )

    @model_validator(mode="after")
    def consistent(self) -> Self:
        try:
            self.config.to_domain()
        except DomainError:
            raise ValueError("invalid policy invariants") from None
        if policy_config_hash(self.config) != self.content_hash:
            raise ValueError("policy content hash mismatch")
        if self.mode == "TEST_DEFAULT":
            if self.config.metadata.status != PolicyStatus.TEST_DEFAULT or any(
                value is not None
                for value in (
                    self.policy_id,
                    self.policy_version_id,
                    self.effective_from,
                    self.approved_by,
                    self.approved_by_actor,
                    self.approved_at,
                )
            ):
                raise ValueError("test policy must not claim an approved identity")
        elif (
            self.config.metadata.status != PolicyStatus.ACTIVE
            or self.policy_id is None
            or self.policy_version_id is None
            or not self.approved_by
            or not self.approved_by.strip()
            or self.approved_by_actor != "HUMAN"
            or self.approved_at is None
            or self.effective_from is None
            or self.approved_at.tzinfo is None
            or self.effective_from.tzinfo is None
            or self.approved_at > self.effective_from
        ):
            raise ValueError("active policy requires an attributable human approval")
        return self

    def require_available(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or (
            self.effective_from is not None and self.effective_from > as_of
        ):
            raise ValueError("policy is not effective at the analysis time")


class AnalysisPolicyPort(Protocol):
    async def policy(
        self, portfolio_id: UUID | None, *, as_of: datetime
    ) -> FrozenAnalysisPolicy: ...


class IntentAllocation(FrozenGovernanceModel):
    intent: RiskIntent
    weight: Decimal


class FrozenSizingFormula(FrozenGovernanceModel):
    status: Literal["TEST_DEFAULT"] = "TEST_DEFAULT"
    version: str
    intent_weights: tuple[IntentAllocation, ...]
    target_volatility: Decimal
    volatility_floor: Decimal
    volatility_scale_min: Decimal
    volatility_scale_max: Decimal
    reduce_fraction: Decimal

    @classmethod
    def capture(cls, formula: SizingFormula) -> "FrozenSizingFormula":
        return cls(
            version=formula.version,
            intent_weights=tuple(
                IntentAllocation(intent=intent, weight=formula.intent_weights[intent].value)
                for intent in sorted(RiskIntent, key=str)
            ),
            target_volatility=formula.target_volatility,
            volatility_floor=formula.volatility_floor,
            volatility_scale_min=formula.volatility_scale_min,
            volatility_scale_max=formula.volatility_scale_max,
            reduce_fraction=formula.reduce_fraction.value,
        )

    @model_validator(mode="after")
    def valid_formula(self) -> Self:
        if len(self.intent_weights) != len(RiskIntent) or {
            w.intent for w in self.intent_weights
        } != set(RiskIntent):
            raise ValueError("every sizing intent must occur exactly once")
        try:
            self.to_domain()
        except DomainError:
            raise ValueError("invalid sizing formula") from None
        return self

    def to_domain(self) -> SizingFormula:
        return SizingFormula(
            version=self.version,
            intent_weights={item.intent: Weight(item.weight) for item in self.intent_weights},
            target_volatility=self.target_volatility,
            volatility_floor=self.volatility_floor,
            volatility_scale_min=self.volatility_scale_min,
            volatility_scale_max=self.volatility_scale_max,
            reduce_fraction=Weight(self.reduce_fraction),
        )


class FrozenPrompt(FrozenGovernanceModel):
    role: AgentRole
    version: str
    content_hash: str
    allowed_tools: tuple[AgentTool, ...]


class AnalysisGovernancePlan(FrozenGovernanceModel):
    schema_version: Literal["1.0"] = "1.0"
    policy: FrozenAnalysisPolicy
    formula: FrozenSizingFormula
    prompts: tuple[FrozenPrompt, ...]
    # No independent, approved StrategyVersion is wired into P6 yet. Never invent one.
    strategy_status: Literal["NOT_CONFIGURED"] = "NOT_CONFIGURED"

    def snapshot(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        entry = payload["policy"]["config"]["entry"]
        entry["require_thesis_states"] = sorted(entry["require_thesis_states"])
        return payload

    @property
    def content_hash(self) -> str:
        return digest(self.snapshot())

    @property
    def allows_new_exposure(self) -> bool:
        # Even an approved policy cannot authorize the still-test-only sizing strategy.
        return False
