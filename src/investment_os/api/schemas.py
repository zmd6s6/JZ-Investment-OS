"""Versioned bootstrap health response schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LivenessResponse(StrictResponse):
    schema_version: Literal["1.0"] = "1.0"
    service: Literal["investment-api"] = "investment-api"
    status: Literal["alive"] = "alive"
    mode: Literal["DEVELOPMENT"] = "DEVELOPMENT"
    live_trading: Literal[False] = False


class ReadinessResponse(StrictResponse):
    schema_version: Literal["1.0"] = "1.0"
    service: Literal["investment-api"] = "investment-api"
    status: Literal["ready", "not_ready"]
    mode: Literal["DEVELOPMENT"] = "DEVELOPMENT"
    live_trading: Literal[False] = False
    checks: dict[str, str]


class OnboardingStateResponse(StrictResponse):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["NOT_STARTED", "IN_PROGRESS"]
    started_at: datetime | None


class ProductCapabilityResponse(StrictResponse):
    key: str
    label: str
    status: Literal["AVAILABLE", "CONFIGURATION_REQUIRED", "NOT_IMPLEMENTED"]
    detail: str


class SystemSettingsResponse(StrictResponse):
    schema_version: Literal["1.0"] = "1.0"
    market_timezone: str
    market_scopes: list[str]
    auto_trade: Literal[False] = False


class SystemSettingsUpdateRequest(StrictResponse):
    market_timezone: str = Field(min_length=1, max_length=64)
    market_scopes: list[str] = Field(default_factory=list, max_length=20)


class ModelProviderProfileRequest(StrictResponse):
    name: str = Field(min_length=1, max_length=255)
    provider_type: str = Field(min_length=1, max_length=128)
    base_url: str = Field(min_length=1, max_length=2048)
    model_name: str = Field(min_length=1, max_length=255)
    timeout_seconds: int = Field(ge=1, le=300)
    max_tokens: int = Field(ge=1, le=200_000)
    enabled: bool = False
    pricing_version: str | None = Field(default=None, max_length=64)
    pricing_currency: str | None = Field(default=None, max_length=16)
    input_token_price: Decimal | None = Field(default=None, ge=0)
    output_token_price: Decimal | None = Field(default=None, ge=0)
    pricing_effective_at: datetime | None = None
    credential: SecretStr | None = Field(
        default=None,
        json_schema_extra={"writeOnly": True},
    )


class ModelProviderProfileResponse(StrictResponse):
    schema_version: Literal["1.0"] = "1.0"
    id: UUID
    name: str
    provider_type: str
    base_url: str
    model_name: str
    timeout_seconds: int
    max_tokens: int
    enabled: bool
    credential_configured: bool
    pricing_version: str | None
    pricing_currency: str | None
    input_token_price: Decimal | None
    output_token_price: Decimal | None
    pricing_effective_at: datetime | None


class DataProviderProfileRequest(StrictResponse):
    name: str = Field(min_length=1, max_length=255)
    provider_type: str = Field(min_length=1, max_length=128)
    base_url: str = Field(min_length=1, max_length=2048)
    timeout_seconds: int = Field(ge=1, le=300)
    enabled: bool = False
    retention_days: int = Field(default=365, ge=1, le=3650)
    credential: SecretStr | None = Field(
        default=None,
        json_schema_extra={"writeOnly": True},
    )


class DataProviderProfileResponse(StrictResponse):
    schema_version: Literal["1.0"] = "1.0"
    id: UUID
    name: str
    provider_type: str
    base_url: str
    timeout_seconds: int
    enabled: bool
    retention_days: int
    credential_configured: bool


class RoleModelAssignmentRequest(StrictResponse):
    model_provider_profile_id: UUID


class RoleModelAssignmentResponse(StrictResponse):
    schema_version: Literal["1.0"] = "1.0"
    role: str
    model_provider_profile_id: UUID


class LLMBudgetPolicyRequest(StrictResponse):
    version: str = Field(min_length=1, max_length=64)
    currency: str = Field(min_length=1, max_length=16)
    task_token_limit: int = Field(gt=0)
    daily_token_limit: int = Field(gt=0)
    task_cost_limit: Decimal = Field(ge=0)
    daily_cost_limit: Decimal = Field(ge=0)


class LLMBudgetUsageResponse(StrictResponse):
    window_date: str
    input_tokens: int
    output_tokens: int
    total_cost: Decimal
    reserved_tokens: int
    reserved_cost: Decimal
    remaining_tokens: int
    remaining_cost: Decimal


class LLMBudgetResponse(StrictResponse):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["CONFIGURED", "NOT_CONFIGURED"]
    version: str | None = None
    currency: str | None = None
    task_token_limit: int | None = None
    daily_token_limit: int | None = None
    task_cost_limit: Decimal | None = None
    daily_cost_limit: Decimal | None = None
    usage: LLMBudgetUsageResponse | None = None


class ProviderTestResponse(StrictResponse):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal[
        "CONFIGURATION_VALID",
        "CREDENTIAL_MISSING",
        "SECRET_STORE_UNAVAILABLE",
        "CONNECTION_SUCCEEDED",
        "CONNECTION_FAILED",
        "UNSUPPORTED_PROVIDER",
    ]
    detail: str
    latency_ms: int | None = Field(default=None, ge=0)


class ProviderTestHistoryResponse(StrictResponse):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal[
        "CONFIGURATION_VALID",
        "CREDENTIAL_MISSING",
        "SECRET_STORE_UNAVAILABLE",
        "CONNECTION_SUCCEEDED",
        "CONNECTION_FAILED",
        "UNSUPPORTED_PROVIDER",
    ]
    occurred_at: datetime
    latency_ms: int | None = Field(default=None, ge=0)


class ProviderSyncHistoryResponse(StrictResponse):
    schema_version: Literal["1.0"] = "1.0"
    occurred_at: datetime
    artifact_count: int = Field(ge=0)
    latency_ms: int = Field(ge=0)


class TaskRunResponse(StrictResponse):
    id: UUID
    task_name: str
    scheduled_for: datetime
    status: str
    attempt: int
    idempotency_key: str
    started_at: datetime
    finished_at: datetime | None
    error: dict[str, str] | None


class DailyReportResponse(StrictResponse):
    id: UUID
    as_of: datetime
    content_hash: str
    rendered_markdown: str
    simulation_only: Literal[True]


class ResearchIngestRequest(StrictResponse):
    provider: str
    provider_ref: str
    artifact_type: str
    source_name: str
    source_locator: str
    source_tier: str
    observed_at: datetime
    effective_at: datetime
    available_at: datetime
    payload: dict[str, object]
    source_schema_version: str
    instrument_id: UUID | None = None
    expires_at: datetime | None = None
    supersedes_id: UUID | None = None


class ResearchIngestResponse(StrictResponse):
    schema_version: Literal["1.0"] = "1.0"
    evidence_id: UUID
    reused: bool


class ProviderResearchFetchRequest(StrictResponse):
    """Explicit owner-requested fetch; it never selects a provider implicitly."""

    query: str = Field(min_length=1, max_length=1_000)
    as_of: datetime
    instrument_ids: list[UUID] = Field(default_factory=list, max_length=100)
    max_results: int = Field(default=10, ge=1, le=20)


class ProviderResearchFetchResponse(StrictResponse):
    schema_version: Literal["1.0"] = "1.0"
    provider_profile_id: UUID
    results: list[ResearchIngestResponse]


class EvidenceClaimResponse(StrictResponse):
    description: str
    evidence_ids: list[UUID]


class ThesisPillarResponse(StrictResponse):
    key: str
    claim: EvidenceClaimResponse
    status: Literal["VALID", "AT_RISK", "INVALID"]


class InvalidationConditionResponse(StrictResponse):
    condition: str
    measurement: str
    threshold: str
    window: str


class ThesisVersionResponse(StrictResponse):
    schema_version: Literal["1.0"] = "1.0"
    instrument_id: UUID
    thesis_id: UUID
    version_id: UUID
    version: int
    parent_version_id: UUID | None
    state: Literal["UNKNOWN", "VALID", "STRENGTHENING", "WEAKENING", "BROKEN"]
    long_term_summary: str
    pillars: list[ThesisPillarResponse]
    catalysts: list[EvidenceClaimResponse]
    risks: list[EvidenceClaimResponse]
    invalidation_conditions: list[InvalidationConditionResponse]
    monitoring_conditions: list[str]
    change_reason: Literal["NEW_EVIDENCE", "SCHEDULED_REVIEW", "EVENT", "HUMAN_CORRECTION"]
    evidence_ids: list[UUID]
    created_at: datetime


class ThesisHistoryResponse(StrictResponse):
    schema_version: Literal["1.0"] = "1.0"
    instrument_id: UUID
    versions: list[ThesisVersionResponse]


class DecisionApprovalResponse(StrictResponse):
    id: UUID
    actor_id: str
    action: Literal["APPROVE", "REJECT", "REVOKE"]
    comment: str | None
    expires_at: datetime | None
    occurred_at: datetime


class DecisionExecutionResponse(StrictResponse):
    id: UUID
    approval_id: UUID
    execution_mode: Literal["PAPER", "MANUAL"]
    status: Literal["PENDING", "PARTIAL", "FILLED", "CANCELLED"]
    requested_quantity: Decimal
    filled_quantity: Decimal
    avg_price: Decimal | None
    external_refs: list[str]
    occurred_at: datetime


class DecisionJournalResponse(StrictResponse):
    """Read-only, versioned reconstruction of one immutable Decision Journal entry."""

    schema_version: Literal["1.0"] = "1.0"
    decision_id: UUID
    instrument_id: UUID
    portfolio_id: UUID
    committee_session_id: UUID | None
    thesis_version_id: UUID | None
    policy_version_id: UUID
    strategy_version_id: UUID
    risk_assessment_id: UUID | None
    position_sizing_run_id: UUID | None
    action: Literal["WATCH", "BUY", "ADD", "HOLD", "REDUCE", "EXIT", "AVOID"]
    confidence: Decimal
    risk_intent: Literal["NONE", "TINY", "SMALL", "NORMAL", "HIGH", "EXIT"]
    core_action: Literal["NONE", "BUY", "ADD", "HOLD", "REDUCE", "EXIT"]
    tactical_action: Literal["NONE", "BUY", "ADD", "HOLD", "REDUCE", "EXIT"]
    state: str
    reasons: list[dict[str, object]]
    risks: list[dict[str, object]]
    watch_conditions: list[str]
    invalidation_conditions: list[str]
    position_before: dict[str, object]
    position_after_proposed: dict[str, object]
    unknowns: list[str]
    dissent: list[str]
    next_review_at: datetime
    input_snapshot_hash: str
    prompt_bundle_version: str
    formula_version: str
    content_hash: str
    version: int
    evidence_ids: list[UUID]
    approvals: list[DecisionApprovalResponse]
    executions: list[DecisionExecutionResponse]
    created_at: datetime
