"""Completed typed research artifacts and a read-only product boundary."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from investment_os.application.agent_registry import PromptBundle
from investment_os.application.agent_runtime import AgentRunResult
from investment_os.application.analysis_context import AnalysisContext
from investment_os.application.committee_runtime import CommitteeSessionResult
from investment_os.application.llm_gateway import LLMGatewayRequest
from investment_os.domain.risk import RiskAssessment


@dataclass(frozen=True, slots=True)
class CompletedResearch:
    context: AnalysisContext
    committee: CommitteeSessionResult
    portfolio_request: LLMGatewayRequest
    portfolio_result: AgentRunResult
    risk_request: LLMGatewayRequest
    risk_result: AgentRunResult
    assessment: RiskAssessment
    started_at: datetime
    completed_at: datetime
    prompts: tuple[PromptBundle, ...]
    schema_version: Literal["1.0"] = "1.0"


class ResearchRecordView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID
    status: Literal["RECORDED", "NOT_RECORDED"]
    committee_session_id: UUID | None = None
    input_hash: str | None = None
    agents: tuple[dict[str, object], ...] = ()
    risk: dict[str, object] | None = None
    decision_status: Literal["NOT_REGISTERED"] = "NOT_REGISTERED"
    limitations: tuple[str, ...] = ()


class AnalysisResearchReader(Protocol):
    async def read(self, run_id: UUID) -> ResearchRecordView: ...
