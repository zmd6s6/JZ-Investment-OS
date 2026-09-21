"""Versioned bootstrap health response schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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
