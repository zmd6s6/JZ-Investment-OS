"""Frozen, deterministic evidence visibility for a single committee analysis."""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.domain.agent import AgentOpinion
from investment_os.domain.values import UtcTimestamp


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


class EvidenceSourceTier(StrEnum):
    PRIMARY = "PRIMARY"
    REPUTABLE_SECONDARY = "REPUTABLE_SECONDARY"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class AnalysisEvidence:
    """Immutable evidence identity and availability metadata, without executable content."""

    evidence_id: UUID
    content_hash: str
    available_at: UtcTimestamp
    source_tier: EvidenceSourceTier = EvidenceSourceTier.OTHER
    independence_key: str = "unknown"

    def __post_init__(self) -> None:
        if not _is_sha256(self.content_hash):
            raise ApplicationError(
                ApplicationErrorCode.AGENT_OPINION_EVIDENCE_UNAVAILABLE,
                "AnalysisContext Evidence requires a lowercase SHA-256 content hash",
            )
        if not self.independence_key.strip():
            raise ApplicationError(
                ApplicationErrorCode.AGENT_OPINION_EVIDENCE_UNAVAILABLE,
                "AnalysisContext Evidence requires a non-blank independence key",
            )


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    instrument_id: UUID
    as_of: UtcTimestamp
    evidence: tuple[AnalysisEvidence, ...]
    input_snapshot_hash: str

    @property
    def visible_evidence_ids(self) -> frozenset[UUID]:
        return frozenset(item.evidence_id for item in self.evidence)


def freeze_analysis_context(
    instrument_id: UUID,
    *,
    as_of: datetime,
    evidence: Iterable[AnalysisEvidence],
) -> AnalysisContext:
    """Freeze only Evidence available at ``as_of`` into a stable content-addressed snapshot."""

    snapshot_time = UtcTimestamp(as_of)
    visible = sorted(
        (item for item in evidence if item.available_at.value <= snapshot_time.value),
        key=lambda item: (str(item.evidence_id), item.content_hash),
    )
    if len({item.evidence_id for item in visible}) != len(visible):
        raise ApplicationError(
            ApplicationErrorCode.AGENT_OPINION_EVIDENCE_UNAVAILABLE,
            "AnalysisContext cannot contain duplicate visible Evidence IDs",
        )
    snapshot = {
        "instrument_id": str(instrument_id),
        "as_of": snapshot_time.value.isoformat(),
        "evidence": [
            {
                "evidence_id": str(item.evidence_id),
                "content_hash": item.content_hash,
                "available_at": item.available_at.value.isoformat(),
                "source_tier": item.source_tier.value,
                "independence_key": item.independence_key,
            }
            for item in visible
        ],
    }
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return AnalysisContext(
        instrument_id=instrument_id,
        as_of=snapshot_time,
        evidence=tuple(visible),
        input_snapshot_hash=sha256(encoded.encode("utf-8")).hexdigest(),
    )


def require_context_evidence(opinion: AgentOpinion, context: AnalysisContext) -> None:
    """Reject an otherwise valid opinion when it cites Evidence outside the frozen snapshot."""

    referenced = {
        evidence_id
        for observation in opinion.observations
        for evidence_id in observation.evidence_ids
    }
    unavailable = referenced - context.visible_evidence_ids
    if unavailable:
        raise ApplicationError(
            ApplicationErrorCode.AGENT_OPINION_EVIDENCE_UNAVAILABLE,
            "AgentOpinion references Evidence unavailable in the frozen AnalysisContext",
            details={"evidence_ids": sorted(str(evidence_id) for evidence_id in unavailable)},
        )
    if opinion.confidence.value > Decimal("0.70"):
        cited = tuple(item for item in context.evidence if item.evidence_id in referenced)
        has_primary = any(item.source_tier is EvidenceSourceTier.PRIMARY for item in cited)
        independent_sources = {item.independence_key for item in cited}
        if not has_primary and len(independent_sources) < 2:
            raise ApplicationError(
                ApplicationErrorCode.AGENT_OPINION_EVIDENCE_UNAVAILABLE,
                "confidence above 0.70 requires one PRIMARY or two independent Evidence sources",
            )
