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


class InstrumentIdentityRequest(StrictResponse):
    market: str = Field(min_length=1, max_length=64)
    symbol: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    asset_type: str = Field(min_length=1, max_length=64)
    currency: str = Field(min_length=3, max_length=3)
    sector: str = Field(default="", max_length=64)


class InstrumentCatalogResponse(StrictResponse):
    instrument_id: UUID
    market: str
    symbol: str
    name: str
    asset_type: str
    currency: str
    sector: str


class PortfolioCreateRequest(StrictResponse):
    name: str = Field(min_length=1, max_length=255)
    base_currency: str = Field(min_length=3, max_length=3)
    cash_balance: Decimal = Decimal("0")


class PortfolioCashUpdateRequest(StrictResponse):
    cash_balance: Decimal


class ManualPositionRequest(StrictResponse):
    market: str = Field(min_length=1, max_length=64)
    symbol: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    asset_type: str = Field(min_length=1, max_length=64)
    currency: str = Field(min_length=3, max_length=3)
    sector: str = Field(default="", max_length=64)
    core_quantity: Decimal = Decimal("0")
    tactical_quantity: Decimal = Decimal("0")
    average_cost: Decimal = Decimal("0")
    core_average_cost: Decimal | None = None
    tactical_average_cost: Decimal | None = None
    core_reason: str = Field(default="", max_length=255)
    tactical_reason: str = Field(default="", max_length=255)
    operation: str = Field(default="MANUAL", max_length=32)


class PortfolioPositionResponse(StrictResponse):
    position_id: UUID
    instrument_id: UUID
    market: str
    symbol: str
    name: str
    asset_type: str
    currency: str
    sector: str
    core_quantity: Decimal
    tactical_quantity: Decimal
    average_cost: Decimal
    core_average_cost: Decimal | None = None
    tactical_average_cost: Decimal | None = None
    core_reason: str = ""
    tactical_reason: str = ""
    operation: str = "MANUAL"


class PortfolioResponse(StrictResponse):
    portfolio_id: UUID
    name: str
    base_currency: str
    cash_balance: Decimal
    status: str
    as_of: datetime
    missing_pricing: bool = True
    positions: list[PortfolioPositionResponse]


class WatchlistItemResponse(StrictResponse):
    watchlist_item_id: UUID
    instrument_id: UUID
    market: str
    symbol: str
    name: str
    asset_type: str
    currency: str
    sector: str
    added_at: datetime
    lifecycle_state: str | None
    thesis_state: str | None
    data_freshness_as_of: datetime | None
    next_monitoring_condition: str | None


class CsvImportRequest(StrictResponse):
    csv_text: str = Field(min_length=1)
    conflict_policy: Literal["SKIP", "REPLACE", "UPDATE"] | None = None
    expected_preview_hash: str | None = None


class CsvRowResultResponse(StrictResponse):
    line_number: int
    status: Literal["VALID", "INVALID", "DUPLICATE", "CONFLICT"]
    reason: str | None
    market: str | None = None
    symbol: str | None = None
    name: str | None = None
    core_quantity: Decimal | None = None
    tactical_quantity: Decimal | None = None
    average_cost: Decimal | None = None
    existing_core_quantity: str | None = None
    existing_tactical_quantity: str | None = None
    existing_average_cost: str | None = None


class CsvImportPreviewResponse(StrictResponse):
    total_rows: int
    can_commit: bool
    requires_conflict_policy: bool
    content_hash: str
    valid: list[CsvRowResultResponse]
    invalid: list[CsvRowResultResponse]
    duplicates: list[CsvRowResultResponse]
    conflicts: list[CsvRowResultResponse]


class CsvImportAppliedRowResponse(StrictResponse):
    line_number: int
    market: str
    symbol: str
    action: Literal["CREATED", "REPLACED", "UPDATED", "SKIPPED"]
    before: dict[str, str] | None
    after: dict[str, str]


class CsvImportCommitResponse(StrictResponse):
    imported_count: int
    skipped_count: int
    conflict_policy: str
    audit_id: UUID
    applied: list[CsvImportAppliedRowResponse]
    portfolio: PortfolioResponse


class PolicyReviewResponse(StrictResponse):
    active_policy_version: str
    policy_status: str
    is_test_default: bool
    limits: list[dict[str, str]]
    warning: str
