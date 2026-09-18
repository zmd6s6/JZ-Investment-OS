"""Versioned bootstrap health response schemas."""

from datetime import datetime
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
