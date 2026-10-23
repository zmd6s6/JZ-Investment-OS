"""运行范围内的历史证据只读端口; 不授予重新分析或交易权限。"""

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class EvidenceCitation(BaseModel):
    # Future snapshot metadata may add fields; the complete raw snapshot hash is checked.
    model_config = ConfigDict(extra="ignore", frozen=True)
    evidence_id: UUID
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_name: str
    source_locator: str
    source_tier: str
    provider: str | None = None
    observed_at: AwareDatetime
    effective_at: AwareDatetime
    available_at: AwareDatetime
    ingested_at: AwareDatetime
    expires_at: AwareDatetime | None
    summary: str
    ingested_freshness_status: str | None = None


class SavedEvidenceText(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    field: Literal["summary", "snippet", "text", "content", "description"]
    text: str
    original_length: int
    truncated: bool


class AnalysisEvidenceView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID
    evidence_id: UUID
    instrument_id: UUID
    analysis_as_of: datetime
    read_at: datetime
    status: Literal["VERIFIED", "NOT_RECORDED", "SNAPSHOT_ONLY", "CONTENT_UNAVAILABLE"]
    input_hash: str | None = None
    citation: EvidenceCitation | None = None
    title: str | None = None
    title_truncated: bool = False
    texts: tuple[SavedEvidenceText, ...] = ()
    freshness_at_run: str | None = None
    freshness_now: str | None = None
    untrusted_content: Literal[True] = True


class AnalysisEvidenceReader(Protocol):
    async def read(self, run_id: UUID, evidence_id: UUID) -> AnalysisEvidenceView: ...
