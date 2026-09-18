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


class ResearchIngestResponse(StrictResponse):
    schema_version: Literal["1.0"] = "1.0"
    evidence_id: UUID
    reused: bool
