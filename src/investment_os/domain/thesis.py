"""Immutable, evidence-backed Thesis content and version primitives."""

import string
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from investment_os.domain.enums import ThesisState
from investment_os.domain.errors import DomainError, DomainErrorCode


class PillarStatus(StrEnum):
    VALID = "VALID"
    AT_RISK = "AT_RISK"
    INVALID = "INVALID"


class ThesisChangeReason(StrEnum):
    NEW_EVIDENCE = "NEW_EVIDENCE"
    SCHEDULED_REVIEW = "SCHEDULED_REVIEW"
    EVENT = "EVENT"
    HUMAN_CORRECTION = "HUMAN_CORRECTION"


def _require_text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise DomainError(
            DomainErrorCode.INVARIANT_VIOLATION,
            f"{field} must not be blank",
        )
    return normalized


def _unique_evidence_ids(evidence_ids: tuple[UUID, ...], field: str) -> tuple[UUID, ...]:
    if not evidence_ids:
        raise DomainError(
            DomainErrorCode.INVARIANT_VIOLATION,
            f"{field} requires at least one Evidence reference",
        )
    if len(set(evidence_ids)) != len(evidence_ids):
        raise DomainError(
            DomainErrorCode.INVARIANT_VIOLATION,
            f"{field} must not repeat an Evidence reference",
        )
    return evidence_ids


@dataclass(frozen=True, slots=True)
class EvidenceBackedClaim:
    description: str
    evidence_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "description", _require_text(self.description, "description"))
        object.__setattr__(
            self,
            "evidence_ids",
            _unique_evidence_ids(self.evidence_ids, "evidence-backed claim"),
        )


@dataclass(frozen=True, slots=True)
class ThesisPillar:
    key: str
    claim: EvidenceBackedClaim
    status: PillarStatus

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _require_text(self.key, "pillar key"))


@dataclass(frozen=True, slots=True)
class InvalidationCondition:
    condition: str
    measurement: str
    threshold: str
    window: str

    def __post_init__(self) -> None:
        for field in ("condition", "measurement", "threshold", "window"):
            object.__setattr__(self, field, _require_text(getattr(self, field), field))


@dataclass(frozen=True, slots=True)
class ThesisContent:
    """Version payload that cannot contain unsupported factual claims."""

    state: ThesisState
    long_term_summary: str
    pillars: tuple[ThesisPillar, ...]
    catalysts: tuple[EvidenceBackedClaim, ...]
    risks: tuple[EvidenceBackedClaim, ...]
    invalidation_conditions: tuple[InvalidationCondition, ...]
    monitoring_conditions: tuple[str, ...]
    change_reason: ThesisChangeReason

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "long_term_summary",
            _require_text(self.long_term_summary, "long-term summary"),
        )
        if not self.pillars:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "a Thesis requires at least one evidence-backed pillar",
            )
        keys = tuple(pillar.key for pillar in self.pillars)
        if len(set(keys)) != len(keys):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "a Thesis must not repeat pillar keys",
            )
        monitoring = tuple(
            _require_text(item, "monitoring condition") for item in self.monitoring_conditions
        )
        object.__setattr__(self, "monitoring_conditions", monitoring)
        if self.state is ThesisState.BROKEN and not self.invalidation_conditions:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "a BROKEN Thesis requires an invalidation condition",
            )

    @property
    def evidence_ids(self) -> tuple[UUID, ...]:
        """Stable, deduplicated provenance in first-reference order."""

        evidence_ids: list[UUID] = []
        for pillar in self.pillars:
            for evidence_id in pillar.claim.evidence_ids:
                if evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)
        for claim in (*self.catalysts, *self.risks):
            claim_ids = claim.evidence_ids
            for evidence_id in claim_ids:
                if evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)
        return tuple(evidence_ids)


@dataclass(frozen=True, slots=True)
class ThesisVersion:
    """An immutable, content-addressed point in a Thesis lineage.

    The application layer computes ``content_hash`` from canonical content.  This domain value
    enforces the lineage shape before persistence, so an invalid version cannot be converted into
    a mutable current-pointer update.
    """

    id: UUID
    thesis_id: UUID
    version: int
    parent_version_id: UUID | None
    content_hash: str
    content: ThesisContent

    def __post_init__(self) -> None:
        if self.version < 1:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "a ThesisVersion must have a positive version number",
            )
        if self.version == 1 and self.parent_version_id is not None:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "the first ThesisVersion must not have a parent version",
            )
        if self.version > 1 and self.parent_version_id is None:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "a successor ThesisVersion requires a parent version",
            )
        if self.parent_version_id == self.id:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "a ThesisVersion must not reference itself as its parent",
            )
        if len(self.content_hash) != 64 or any(
            character not in string.hexdigits for character in self.content_hash
        ):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "a ThesisVersion content hash must be a 64-character hexadecimal SHA-256 digest",
            )
        object.__setattr__(self, "content_hash", self.content_hash.lower())
