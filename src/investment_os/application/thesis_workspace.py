"""Strict human research commands; no state promotion or model authorization."""

import json
from datetime import datetime
from hashlib import sha256
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from investment_os.application.thesis import (
    ThesisSemanticDiff,
    semantic_diff,
    thesis_content_payload,
)
from investment_os.domain.enums import ThesisState
from investment_os.domain.errors import DomainError
from investment_os.domain.thesis import (
    EvidenceBackedClaim,
    InvalidationCondition,
    PillarStatus,
    ThesisChangeReason,
    ThesisContent,
    ThesisPillar,
)

Text = Annotated[str, StringConstraints(min_length=1, max_length=4000, strip_whitespace=True)]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClaimInput(StrictModel):
    description: Text
    evidence_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=100)]

    def domain(self) -> EvidenceBackedClaim:
        return EvidenceBackedClaim(self.description, self.evidence_ids)


class PillarInput(StrictModel):
    key: Annotated[str, Field(min_length=1, max_length=80)]
    claim: ClaimInput
    status: PillarStatus


class ConditionInput(StrictModel):
    condition: Text
    measurement: Text
    threshold: Text
    window: Text


class ThesisDraft(StrictModel):
    state: ThesisState
    long_term_summary: Text
    pillars: Annotated[tuple[PillarInput, ...], Field(min_length=1, max_length=30)]
    catalysts: Annotated[tuple[ClaimInput, ...], Field(max_length=30)]
    risks: Annotated[tuple[ClaimInput, ...], Field(max_length=30)]
    invalidation_conditions: Annotated[tuple[ConditionInput, ...], Field(max_length=30)]
    monitoring_conditions: Annotated[tuple[Text, ...], Field(max_length=30)]
    change_reason: ThesisChangeReason

    def domain(self) -> ThesisContent:
        return ThesisContent(
            state=self.state,
            long_term_summary=self.long_term_summary,
            pillars=tuple(ThesisPillar(p.key, p.claim.domain(), p.status) for p in self.pillars),
            catalysts=tuple(c.domain() for c in self.catalysts),
            risks=tuple(c.domain() for c in self.risks),
            invalidation_conditions=tuple(
                InvalidationCondition(**c.model_dump()) for c in self.invalidation_conditions
            ),
            monitoring_conditions=self.monitoring_conditions,
            change_reason=self.change_reason,
        )


class ThesisCommand(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID
    instrument_id: UUID
    expected_version_id: UUID | None
    expected_content_hash: Hash | None
    actor_name: Annotated[str, Field(min_length=1, max_length=120, pattern=r".*\S.*")]
    draft: ThesisDraft

    @model_validator(mode="after")
    def baseline_pair(self) -> "ThesisCommand":
        if (self.expected_version_id is None) != (self.expected_content_hash is None):
            raise ValueError("baseline version and hash must both be set or both null")
        try:
            self.draft.domain()
        except DomainError as error:
            raise ValueError(str(error)) from error
        return self

    def canonical_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude={"draft"})
        payload["draft"] = thesis_content_payload(self.draft.domain())
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()


class SavedThesis(StrictModel):
    thesis_id: UUID
    version_id: UUID
    version: int
    parent_version_id: UUID | None
    content_hash: Hash
    created_at: datetime
    draft: ThesisDraft
    semantic_diff: dict[str, object] | None


class ThesisEvidence(StrictModel):
    evidence_id: UUID
    source_name: str
    source_locator: str
    observed_at: datetime
    effective_at: datetime
    available_at: datetime
    ingested_at: datetime
    expires_at: datetime | None
    content_hash: str
    quality_score: str
    eligible: bool
    reason: str | None
    excerpt: str


class ThesisWorkspace(StrictModel):
    instrument_id: UUID
    current: SavedThesis | None
    history: tuple[SavedThesis, ...]
    evidence: tuple[ThesisEvidence, ...]
    evidence_limit: int = 100


class ThesisPreview(StrictModel):
    command_hash: Hash
    content_hash: Hash
    material: bool
    differences: dict[str, object]
    checked_at: datetime


class ThesisReceipt(StrictModel):
    request_id: UUID
    instrument_id: UUID
    command_hash: Hash
    created: bool
    saved: SavedThesis


class ThesisWorkspacePort(Protocol):
    async def read(self, instrument_id: UUID) -> ThesisWorkspace: ...
    async def preview(self, command: ThesisCommand) -> ThesisPreview: ...
    async def save(self, command: ThesisCommand) -> ThesisReceipt: ...


def workspace_semantic_diff(previous: ThesisContent, current: ThesisContent) -> ThesisSemanticDiff:
    """Compare human commands using the canonical persisted-content interpretation."""
    canonical_previous = ThesisDraft.model_validate(thesis_content_payload(previous)).domain()
    canonical_current = ThesisDraft.model_validate(thesis_content_payload(current)).domain()
    return semantic_diff(canonical_previous, canonical_current)
