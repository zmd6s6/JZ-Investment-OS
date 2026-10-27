"""Versioned input, lifecycle and shadow-result boundary for PRODUCT-06 analysis."""

from datetime import datetime
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

from investment_os.application.portfolio_valuation import ValuationContext
from investment_os.domain.agent import AgentRole
from investment_os.domain.analysis_run import AnalysisStatus
from investment_os.domain.enums import Action, RiskIntent

ANALYSIS_ROLES = tuple(role for role in AgentRole if role is not AgentRole.REVIEW)


class AnalysisCancelled(RuntimeError):
    pass


class AnalysisLeaseLost(RuntimeError):
    pass


class AnalysisDto(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AnalysisStart(AnalysisDto):
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID
    portfolio_id: UUID
    instrument_id: UUID
    model_profiles: dict[AgentRole, UUID]
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    data_profile_ids: tuple[UUID, ...] = Field(default=(), max_length=3)
    query: str | None = Field(default=None, min_length=1, max_length=300)
    max_results: int = Field(default=5, ge=1, le=5)
    market_source: Literal["MANUAL_MARKET"] = "MANUAL_MARKET"
    market_source_name: str = Field(min_length=1, max_length=255)
    allow_model_calls: Literal[True]
    allow_data_calls: StrictBool = False
    retry_of: UUID | None = None

    @field_validator("allow_model_calls", mode="before")
    @classmethod
    def explicit_model_consent(cls, value: object) -> object:
        if value is not True:
            raise ValueError("explicit boolean model consent is required")
        return value

    @model_validator(mode="after")
    def explicit_inputs(self) -> Self:
        if set(self.model_profiles) != set(ANALYSIS_ROLES):
            raise ValueError("all analysis roles require an explicit model profile")
        if len(set(self.evidence_ids)) != len(self.evidence_ids) or len(
            set(self.data_profile_ids)
        ) != len(self.data_profile_ids):
            raise ValueError("duplicate explicit inputs")
        if self.data_profile_ids and (
            not self.allow_data_calls or not self.query or not self.query.strip()
        ):
            raise ValueError("selected data calls require an explicit query and consent")
        if not self.market_source_name.strip():
            raise ValueError("market source name is required")
        return self


class SelectedModel(AnalysisDto):
    profile_id: UUID
    name: str
    model_name: str
    config_hash: str
    timeout_seconds: int
    max_tokens: int


class SelectedData(AnalysisDto):
    profile_id: UUID
    name: str
    provider_type: str
    config_hash: str


class AnalysisQueuedInput(AnalysisDto):
    command: AnalysisStart
    queued_at: AwareDatetime
    valuation: ValuationContext
    models: dict[AgentRole, SelectedModel]
    data_profiles: tuple[SelectedData, ...]
    budget_hash: str


class AnalysisEvidenceInput(AnalysisDto):
    evidence_id: UUID
    instrument_id: UUID | None
    content_hash: str
    source_name: str
    source_locator: str
    source_tier: str
    observed_at: AwareDatetime
    effective_at: AwareDatetime
    available_at: AwareDatetime
    ingested_at: AwareDatetime
    expires_at: AwareDatetime | None
    quality_score: str
    freshness: str
    payload_json: str


class AnalysisFrozenInput(AnalysisDto):
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID
    as_of: AwareDatetime
    instrument_id: UUID
    queued: AnalysisQueuedInput
    evidence: tuple[AnalysisEvidenceInput, ...]
    thesis_version_id: UUID | None
    thesis_state: str
    thesis_json: str | None
    input_hash: str
    blockers: tuple[str, ...] = ()
    feature_set_version: Literal["evidence-count-v1"] = "evidence-count-v1"
    prompt_bundle_version: Literal["analysis-runtime-v1"] = "analysis-runtime-v1"


class EvidenceReason(AnalysisDto):
    text: str = Field(min_length=1, max_length=4000)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)


class PortfolioIntent(AnalysisDto):
    schema_version: Literal["portfolio-intent-1.0"]
    risk_intent: RiskIntent
    reasons: tuple[EvidenceReason, ...] = Field(min_length=1, max_length=20)
    unknowns: tuple[str, ...] = Field(default=(), max_length=50)


class CioProposal(AnalysisDto):
    schema_version: Literal["cio-proposal-1.0"]
    proposed_action: Action
    reasons: tuple[EvidenceReason, ...] = Field(min_length=1, max_length=20)
    unknowns: tuple[str, ...] = Field(default=(), max_length=50)


class ShadowDecision(AnalysisDto):
    schema_version: Literal["analysis-shadow-1.0"] = "analysis-shadow-1.0"
    action: Action
    risk_intent: RiskIntent
    risk_gate: Literal["UNKNOWN", "VETO", "PASS"]
    policy_version_id: UUID | None
    thesis_version_id: UUID | None
    sizing_run_id: UUID | None = None
    sizing_status: Literal["BLOCKED"] = "BLOCKED"
    target_quantity: None = None
    delta_quantity: None = None
    reasons: tuple[EvidenceReason, ...]
    blockers: tuple[str, ...]
    input_hash: str
    execution_allowed: Literal[False] = False
    auto_trade: Literal[False] = False

    @model_validator(mode="after")
    def blocked_sizing_cannot_increase_exposure(self) -> Self:
        if self.action in {Action.BUY, Action.ADD}:
            raise ValueError("missing sizing cannot authorize new exposure")
        return self


class AnalysisStep(AnalysisDto):
    sequence: int
    stage: str
    status: Literal["RUNNING", "COMPLETED", "BLOCKED", "FAILED"]
    occurred_at: AwareDatetime
    reason_code: str | None = None
    payload: dict[str, object]


class AnalysisRunView(AnalysisDto):
    run_id: UUID
    request_id: UUID
    portfolio_id: UUID
    instrument_id: UUID
    status: AnalysisStatus
    queued_at: AwareDatetime
    started_at: AwareDatetime | None
    finished_at: AwareDatetime | None
    cancel_requested: bool
    retry_of: UUID | None
    error_code: str | None
    request_hash: str
    input_hash: str | None
    policy_version_id: UUID | None
    request: AnalysisStart | None = None
    steps: tuple[AnalysisStep, ...] = ()
    frozen_input: AnalysisFrozenInput | None = None
    shadow_decision: ShadowDecision | None = None


class AnalysisStorePort(Protocol):
    async def find_request(self, request_id: UUID) -> AnalysisRunView | None: ...

    async def enqueue(self, snapshot: AnalysisQueuedInput) -> AnalysisRunView: ...
    async def get(self, run_id: UUID) -> AnalysisRunView: ...
    async def list_runs(
        self, *, portfolio_id: UUID | None = None, limit: int = 30
    ) -> tuple[AnalysisRunView, ...]: ...
    async def cancel(self, run_id: UUID) -> AnalysisRunView: ...
    async def claim_next(self) -> tuple[UUID, UUID, AnalysisQueuedInput] | None: ...
    async def check_running(self, run_id: UUID, lease: UUID) -> None: ...
    async def freeze(self, run_id: UUID, lease: UUID, value: AnalysisFrozenInput) -> None: ...
    async def step(
        self,
        run_id: UUID,
        lease: UUID,
        *,
        stage: str,
        status: str,
        payload: dict[str, object],
        reason_code: str | None = None,
    ) -> None: ...
    async def finish(
        self,
        run_id: UUID,
        lease: UUID,
        *,
        status: AnalysisStatus,
        error_code: str | None = None,
        result: ShadowDecision | None = None,
    ) -> None: ...
    async def expire_interrupted(self, *, older_than: datetime) -> int: ...
