"""Explicit human-authored Thesis commands, separate from model analysis and approvals."""

from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from investment_os.application.thesis_review import (
    TeamThesisProvenance,
    TeamThesisReview,
    TeamThesisSource,
)
from investment_os.domain.enums import ThesisState
from investment_os.domain.thesis import (
    EvidenceBackedClaim,
    InvalidationCondition,
    PillarStatus,
    ThesisChangeReason,
    ThesisContent,
    ThesisPillar,
)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=3000)]
Key = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class ThesisDto(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ThesisClaimInput(ThesisDto):
    description: Text
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=50)

    def to_domain(self) -> EvidenceBackedClaim:
        return EvidenceBackedClaim(self.description, self.evidence_ids)


class ThesisPillarInput(ThesisDto):
    key: Key
    claim: ThesisClaimInput
    status: PillarStatus


class ThesisInvalidationInput(ThesisDto):
    condition: Text
    measurement: Text
    threshold: Text
    window: Text


class ThesisContentInput(ThesisDto):
    state: ThesisState
    long_term_summary: Text
    pillars: tuple[ThesisPillarInput, ...] = Field(min_length=1, max_length=20)
    catalysts: tuple[ThesisClaimInput, ...] = Field(max_length=20)
    risks: tuple[ThesisClaimInput, ...] = Field(max_length=20)
    invalidation_conditions: tuple[ThesisInvalidationInput, ...] = Field(max_length=20)
    monitoring_conditions: tuple[Text, ...] = Field(max_length=20)
    change_reason: ThesisChangeReason

    def to_domain(self) -> ThesisContent:
        return ThesisContent(
            state=self.state,
            long_term_summary=self.long_term_summary,
            pillars=tuple(ThesisPillar(p.key, p.claim.to_domain(), p.status) for p in self.pillars),
            catalysts=tuple(c.to_domain() for c in self.catalysts),
            risks=tuple(c.to_domain() for c in self.risks),
            invalidation_conditions=tuple(
                InvalidationCondition(c.condition, c.measurement, c.threshold, c.window)
                for c in self.invalidation_conditions
            ),
            monitoring_conditions=self.monitoring_conditions,
            change_reason=self.change_reason,
        )


class SaveThesisCommand(ThesisDto):
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID
    expected_version_id: UUID | None
    content: ThesisContentInput
    review_source: TeamThesisSource | None = None


class ThesisSaved(ThesisDto):
    schema_version: Literal["1.0"] = "1.0"
    thesis_id: UUID
    version_id: UUID
    version: int
    content_hash: str
    created: bool


class ThesisWorkspaceVersion(ThesisDto):
    id: UUID
    version: int
    parent_version_id: UUID | None
    content_hash: str
    created_at: str
    content: ThesisContentInput
    semantic_diff: dict[str, object] | None = None
    review_sources: tuple[TeamThesisProvenance, ...] = ()


class ThesisWorkspace(ThesisDto):
    schema_version: Literal["1.0"] = "1.0"
    instrument_id: UUID
    current_version_id: UUID | None
    versions: tuple[ThesisWorkspaceVersion, ...]


class ThesisProductPort(Protocol):
    async def team_review(self, run_id: UUID) -> TeamThesisReview: ...
    async def workspace(self, instrument_id: UUID) -> ThesisWorkspace: ...
    async def save(self, instrument_id: UUID, command: SaveThesisCommand) -> ThesisSaved: ...


class ThesisProductService:
    def __init__(self, port: ThesisProductPort):
        self._port = port

    async def team_review(self, run_id: UUID) -> TeamThesisReview:
        return await self._port.team_review(run_id)

    async def workspace(self, instrument_id: UUID) -> ThesisWorkspace:
        return await self._port.workspace(instrument_id)

    async def save(self, instrument_id: UUID, command: SaveThesisCommand) -> ThesisSaved:
        command.content.to_domain()
        return await self._port.save(instrument_id, command)
