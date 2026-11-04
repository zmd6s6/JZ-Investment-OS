"""Explicit, versioned Decision eligibility; numeric PASS alone is never permission."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictBool, field_validator, model_validator

from investment_os.application.analysis_risk_sizing import NumericDto, RiskSizingView, exact_number
from investment_os.application.decision_engine import GateOutcome
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.domain.enums import Action

GateName = Literal["INVESTMENT_QUALITY", "TIMING", "PORTFOLIO_FIT"]
GATE_NAMES: tuple[GateName, ...] = ("INVESTMENT_QUALITY", "TIMING", "PORTFOLIO_FIT")


class DecisionGateRule(NumericDto):
    metric: str = Field(min_length=1, max_length=80, pattern=r"^[A-Z][A-Z0-9_]*$")
    comparison: Literal["GTE", "GT", "LTE", "LT", "EQ"]
    threshold: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def exact_threshold(self) -> Self:
        exact_number(self.threshold)
        return self

    def passes(self, value: Decimal) -> bool:
        limit = exact_number(self.threshold)
        return {
            "GTE": value >= limit,
            "GT": value > limit,
            "LTE": value <= limit,
            "LT": value < limit,
            "EQ": value == limit,
        }[self.comparison]


class StrategyDecisionRules(NumericDto):
    """No real coefficients or implied activation; every rule must be supplied explicitly."""

    schema_version: Literal["strategy-decision-rules-1.0"]
    allow_decision_proposals: Literal[True]
    simulation_only: StrictBool
    portfolio_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)
    instrument_ids: tuple[UUID, ...] = Field(min_length=1, max_length=200)
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    review_after_seconds: int = Field(ge=1, le=31536000, strict=True)
    gates: dict[GateName, tuple[DecisionGateRule, ...]]

    @field_validator("allow_decision_proposals", mode="before")
    @classmethod
    def explicit_permission(cls, value: object) -> object:
        if value is not True:
            raise ValueError("explicit boolean proposal permission required")
        return value

    @model_validator(mode="after")
    def explicit_complete_rules(self) -> Self:
        if set(self.gates) != set(GATE_NAMES) or any(not rules for rules in self.gates.values()):
            raise ValueError("all three gates require explicit nonempty rules")
        if self.valid_until <= self.valid_from:
            raise ValueError("strategy validity must be a nonempty half-open interval")
        if len(set(self.portfolio_ids)) != len(self.portfolio_ids) or len(
            set(self.instrument_ids)
        ) != len(self.instrument_ids):
            raise ValueError("strategy scope cannot contain duplicates")
        return self


class DecisionGateFact(NumericDto):
    metric: str = Field(min_length=1, max_length=80, pattern=r"^[A-Z][A-Z0-9_]*$")
    value: str = Field(min_length=1, max_length=100)
    evidence_id: UUID
    evidence_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def exact_value(self) -> Self:
        exact_number(self.value)
        return self


class StrategyDecisionSnapshot(NumericDto):
    strategy_version_id: UUID
    version: int = Field(ge=1)
    status: str
    approved_by: str | None
    approved_at: AwareDatetime | None
    prompt_bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_ref: str = Field(min_length=1, max_length=255)
    rules: StrategyDecisionRules
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    def expected_content_hash(self) -> str:
        return fingerprint(self.model_dump(mode="json", exclude={"content_hash"}))


class DecisionQualification(NumericDto):
    """Trusted typed source port result, never a model/provider-declared verified boolean."""

    schema_version: Literal["decision-qualification-1.0"]
    qualification_id: UUID
    portfolio_id: UUID
    instrument_id: UUID
    policy_version_id: UUID
    numeric_snapshot_id: UUID
    portfolio_identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    strategy_version_id: UUID
    strategy_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_kind: Literal["SYNTHETIC_FIXTURE", "REFERENCE_ONLY"]
    source_name: str = Field(min_length=1, max_length=255)
    as_of: AwareDatetime
    created_at: AwareDatetime
    expires_at: AwareDatetime
    facts: tuple[DecisionGateFact, ...] = Field(min_length=1, max_length=100)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def unambiguous_facts(self) -> Self:
        if len({fact.metric for fact in self.facts}) != len(self.facts):
            raise ValueError("duplicate gate metrics cannot override one another")
        if self.expires_at <= self.as_of:
            raise ValueError("qualification expiry must follow its as-of")
        return self

    def expected_content_hash(self) -> str:
        return fingerprint(self.model_dump(mode="json", exclude={"content_hash"}))


class DecisionBridgeScope(NumericDto):
    portfolio_id: UUID
    instrument_id: UUID
    policy_version_id: UUID | None
    numeric_snapshot_id: UUID | None
    portfolio_identity_hash: str
    captured_at: AwareDatetime
    queued_at: AwareDatetime
    # A daily cost/Shadow authorization is not authorization for an investment proposal.
    scheduled_shadow: StrictBool


class DecisionBridgeView(NumericDto):
    schema_version: Literal["analysis-decision-bridge-1.0"] = "analysis-decision-bridge-1.0"
    status: Literal["BLOCKED", "READY_FOR_RECONSTRUCTION", "PENDING_APPROVAL"] = "BLOCKED"
    decision_id: UUID | None = None
    qualification_id: UUID | None = None
    strategy_version_id: UUID | None = None
    gates: dict[GateName, GateOutcome] = Field(default_factory=dict)
    blockers: tuple[str, ...] = ()
    evaluated_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    simulation_only: Literal[True] = True
    execution_allowed: Literal[False] = False
    auto_trade: Literal[False] = False


class DecisionQualificationPort(Protocol):
    async def get(self, qualification_id: UUID) -> DecisionQualification: ...
    async def list(
        self, portfolio_id: UUID, instrument_id: UUID
    ) -> tuple[DecisionQualification, ...]: ...


def evaluate_decision_readiness(
    *,
    scope: DecisionBridgeScope,
    qualification: DecisionQualification | None,
    strategy: StrategyDecisionSnapshot | None,
    numeric: RiskSizingView | None,
    action: Action,
    evaluated_at: datetime,
) -> DecisionBridgeView:
    """Only explicit qualified rules can close the three gates left UNKNOWN by MVP-205."""
    blockers: list[str] = []
    gates = {gate: GateOutcome.UNKNOWN for gate in GATE_NAMES}
    expires: list[datetime] = []
    if scope.scheduled_shadow:
        blockers.append("SCHEDULED_SHADOW_CANNOT_CREATE_INVESTMENT_DECISION")
    if qualification is None:
        blockers.append("DECISION_QUALIFICATION_NOT_SELECTED")
    if strategy is None:
        blockers.append("DECISION_STRATEGY_VERSION_UNAVAILABLE")
    if numeric is None or numeric.sizing_status != "COMPUTED" or numeric.blockers:
        blockers.append("DECISION_NUMERIC_CHAIN_NOT_READY")
    elif numeric.risk_assessment_id is None or numeric.sizing_run_id is None:
        blockers.append("DECISION_STANDARD_RISK_SIZING_IDS_MISSING")
    if numeric is not None:
        if (
            numeric.numeric_snapshot_id != scope.numeric_snapshot_id
            or numeric.policy_version_id != scope.policy_version_id
        ):
            blockers.append("DECISION_NUMERIC_SCOPE_MISMATCH")
        if numeric.expires_at is None or evaluated_at >= numeric.expires_at:
            blockers.append("DECISION_RISK_EXPIRED")
        else:
            expires.append(numeric.expires_at)
        if numeric.risk_gate == "UNKNOWN":
            blockers.append("DECISION_RISK_UNKNOWN")
        if numeric.risk_gate == "VETO" and action in {Action.BUY, Action.ADD}:
            blockers.append("DECISION_RISK_VETO")
    if qualification is not None:
        if qualification.content_hash != qualification.expected_content_hash():
            blockers.append("DECISION_QUALIFICATION_HASH_MISMATCH")
        if qualification.source_kind != "SYNTHETIC_FIXTURE":
            blockers.append("DECISION_REFERENCE_SOURCE_NOT_QUALIFIED")
        if (
            qualification.portfolio_id != scope.portfolio_id
            or qualification.instrument_id != scope.instrument_id
            or qualification.policy_version_id != scope.policy_version_id
            or qualification.numeric_snapshot_id != scope.numeric_snapshot_id
            or qualification.portfolio_identity_hash != scope.portfolio_identity_hash
        ):
            blockers.append("DECISION_QUALIFICATION_SCOPE_MISMATCH")
        if qualification.created_at > scope.queued_at or qualification.as_of > scope.captured_at:
            blockers.append("DECISION_QUALIFICATION_NOT_AVAILABLE_AT_CAPTURE")
        if evaluated_at >= qualification.expires_at:
            blockers.append("DECISION_QUALIFICATION_EXPIRED")
        expires.append(qualification.expires_at)
    if strategy is not None:
        rules = strategy.rules
        if (
            strategy.status != "ACTIVE"
            or not strategy.approved_by
            or strategy.approved_at is None
            or strategy.approved_at > scope.captured_at
        ):
            blockers.append("DECISION_STRATEGY_NOT_APPROVED")
        if strategy.content_hash != strategy.expected_content_hash():
            blockers.append("DECISION_STRATEGY_HASH_MISMATCH")
        if not rules.simulation_only:
            blockers.append("DECISION_REAL_QUALIFIED_SOURCE_NOT_AVAILABLE")
        if (
            scope.portfolio_id not in rules.portfolio_ids
            or scope.instrument_id not in rules.instrument_ids
        ):
            blockers.append("DECISION_OUTSIDE_APPROVED_STRATEGY_SCOPE")
        if not rules.valid_from <= scope.captured_at <= evaluated_at < rules.valid_until:
            blockers.append("DECISION_STRATEGY_OUTSIDE_VALIDITY")
        expires.extend(
            (rules.valid_until, evaluated_at + timedelta(seconds=rules.review_after_seconds))
        )
    if qualification is not None and strategy is not None:
        if (
            qualification.strategy_version_id != strategy.strategy_version_id
            or qualification.strategy_content_hash != strategy.content_hash
        ):
            blockers.append("DECISION_FIXED_STRATEGY_MISMATCH")
        if not blockers:
            facts = {fact.metric: fact for fact in qualification.facts}
            for gate, gate_rules in strategy.rules.gates.items():
                if any(rule.metric not in facts for rule in gate_rules):
                    blockers.append(f"DECISION_GATE_INPUT_MISSING:{gate}")
                else:
                    gates[gate] = (
                        GateOutcome.PASS
                        if all(
                            rule.passes(exact_number(facts[rule.metric].value))
                            for rule in gate_rules
                        )
                        else GateOutcome.FAIL
                    )
                    if gates[gate] is not GateOutcome.PASS and action not in {
                        Action.REDUCE,
                        Action.EXIT,
                    }:
                        blockers.append(f"DECISION_GATE_NOT_PASSED:{gate}")
    return DecisionBridgeView(
        status="BLOCKED" if blockers else "READY_FOR_RECONSTRUCTION",
        qualification_id=qualification.qualification_id if qualification else None,
        strategy_version_id=strategy.strategy_version_id if strategy else None,
        gates=gates,
        blockers=tuple(sorted(set(blockers))),
        evaluated_at=evaluated_at,
        expires_at=min(expires) if expires else None,
    )
