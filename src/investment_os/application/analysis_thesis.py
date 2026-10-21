"""Frozen historical Thesis inputs; absence is UNKNOWN, never an invented valid thesis."""

from datetime import datetime
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from investment_os.application.thesis import thesis_content_hash
from investment_os.domain.enums import ThesisState
from investment_os.domain.errors import DomainError
from investment_os.domain.thesis import ThesisContent, ThesisVersion


class FrozenThesisModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ThesisEvidenceInput(FrozenThesisModel):
    evidence_id: UUID
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    available_at: datetime
    ingested_at: datetime
    expires_at: datetime | None
    freshness: Literal["FRESH", "STALE", "EXPIRED", "NOT_YET_AVAILABLE"]


class AnalysisThesisVersion(FrozenThesisModel):
    id: UUID
    thesis_id: UUID
    version: int
    parent_version_id: UUID | None
    created_at: datetime
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: ThesisContent

    @model_validator(mode="after")
    def valid_content(self) -> Self:
        try:
            ThesisVersion(
                self.id,
                self.thesis_id,
                self.version,
                self.parent_version_id,
                self.content_hash,
                self.content,
            )
        except DomainError:
            raise ValueError("invalid Thesis lineage") from None
        if thesis_content_hash(self.content) != self.content_hash:
            raise ValueError("Thesis content hash mismatch")
        return self


class AnalysisThesisInput(FrozenThesisModel):
    schema_version: Literal["1.0"] = "1.0"
    instrument_id: UUID
    as_of: datetime
    version: AnalysisThesisVersion | None = None
    evidence: tuple[ThesisEvidenceInput, ...] = ()

    @model_validator(mode="after")
    def valid_snapshot(self) -> Self:
        if self.as_of.tzinfo is None:
            raise ValueError("Thesis as_of must be aware")
        if self.version is None:
            if self.evidence:
                raise ValueError("missing Thesis must not claim evidence")
            return self
        if self.version.created_at.tzinfo is None or self.version.created_at > self.as_of:
            raise ValueError("Thesis was unavailable at as_of")
        if len({e.evidence_id for e in self.evidence}) != len(self.evidence) or {
            e.evidence_id for e in self.evidence
        } != set(self.version.content.evidence_ids):
            raise ValueError("Thesis evidence links differ from its claims")
        for item in self.evidence:
            if any(
                t.tzinfo is None or t > self.as_of for t in (item.available_at, item.ingested_at)
            ):
                raise ValueError("Thesis evidence was unavailable at as_of")
            if item.expires_at is not None and item.expires_at.tzinfo is None:
                raise ValueError("Thesis expiry must be aware")
            if (
                item.expires_at is not None
                and item.expires_at <= self.as_of
                and item.freshness != "EXPIRED"
            ):
                raise ValueError("expired Thesis evidence cannot be marked fresh")
        return self

    @property
    def state(self) -> ThesisState:
        if self.version is None:
            return ThesisState.UNKNOWN
        state = self.version.content.state
        # Old facts cannot authorize new exposure. A known BROKEN thesis stays restrictive.
        if state is not ThesisState.BROKEN and any(e.freshness != "FRESH" for e in self.evidence):
            return ThesisState.UNKNOWN
        return state

    def snapshot(self) -> dict[str, object]:
        return {**self.model_dump(mode="json"), "effective_state": self.state.value}


class AnalysisThesisPort(Protocol):
    async def thesis(self, instrument_id: UUID, *, as_of: datetime) -> AnalysisThesisInput: ...
