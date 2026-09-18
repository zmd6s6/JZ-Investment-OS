"""Deterministic Evidence normalization, freshness, and feature primitives."""

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from investment_os.application.research import ResearchArtifactDTO
from investment_os.domain.values import UtcTimestamp

_EVIDENCE_TYPES = frozenset(
    {"FILING", "FINANCIAL", "MARKET", "MACRO", "INDUSTRY", "NEWS", "EVENT", "DERIVED_FEATURE"}
)
_SOURCE_TIER_QUALITY = {
    "PRIMARY": Decimal("0.95"),
    "REPUTABLE_SECONDARY": Decimal("0.80"),
    "OTHER": Decimal("0.50"),
}


class FreshnessStatus(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    NOT_YET_AVAILABLE = "NOT_YET_AVAILABLE"


@dataclass(frozen=True, slots=True)
class NormalizedEvidence:
    instrument_id: UUID | None
    evidence_type: str
    source_name: str
    source_locator: str
    source_tier: str
    observed_at: UtcTimestamp
    effective_at: UtcTimestamp
    available_at: UtcTimestamp
    ingested_at: UtcTimestamp
    expires_at: UtcTimestamp | None
    quality_score: Decimal
    freshness_status: FreshnessStatus
    payload: Mapping[str, object]
    content_hash: str
    provider: str
    provider_ref: str
    source_schema_version: str
    supersedes_id: UUID | None


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    instrument_id: UUID
    as_of: UtcTimestamp
    feature_set_version: str
    values: Mapping[str, str]
    input_hash: str


def _canonical_hash(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def normalize_artifact(
    artifact: ResearchArtifactDTO, *, ingested_at: datetime
) -> NormalizedEvidence:
    """Create a fail-closed immutable Evidence candidate from one external artifact."""

    evidence_type = artifact.artifact_type.upper()
    source_tier = artifact.source_tier.upper()
    if evidence_type not in _EVIDENCE_TYPES:
        raise ValueError(f"unsupported evidence type: {artifact.artifact_type}")
    if source_tier not in _SOURCE_TIER_QUALITY:
        raise ValueError(f"unsupported source tier: {artifact.source_tier}")
    if not all(
        (artifact.provider, artifact.provider_ref, artifact.source_name, artifact.source_locator)
    ):
        raise ValueError("provider and source provenance fields must be non-empty")

    ingested = UtcTimestamp(ingested_at)
    expires_at = artifact.expires_at
    if artifact.available_at.value > ingested.value:
        freshness = FreshnessStatus.NOT_YET_AVAILABLE
        quality = Decimal("0")
    elif expires_at is not None and expires_at.value <= ingested.value:
        freshness = FreshnessStatus.STALE
        quality = _SOURCE_TIER_QUALITY[source_tier] / Decimal("2")
    else:
        freshness = FreshnessStatus.FRESH
        quality = _SOURCE_TIER_QUALITY[source_tier]

    content = {
        "provider": artifact.provider,
        "provider_ref": artifact.provider_ref,
        "artifact_type": evidence_type,
        "source_name": artifact.source_name,
        "source_locator": artifact.source_locator,
        "source_schema_version": artifact.source_schema_version,
        "observed_at": artifact.observed_at.value.isoformat(),
        "effective_at": artifact.effective_at.value.isoformat(),
        "available_at": artifact.available_at.value.isoformat(),
        "payload": dict(artifact.payload),
    }
    return NormalizedEvidence(
        instrument_id=artifact.instrument_id,
        evidence_type=evidence_type,
        source_name=artifact.source_name,
        source_locator=artifact.source_locator,
        source_tier=source_tier,
        observed_at=artifact.observed_at,
        effective_at=artifact.effective_at,
        available_at=artifact.available_at,
        ingested_at=ingested,
        expires_at=expires_at,
        quality_score=quality,
        freshness_status=freshness,
        payload=dict(artifact.payload),
        content_hash=_canonical_hash(content),
        provider=artifact.provider,
        provider_ref=artifact.provider_ref,
        source_schema_version=artifact.source_schema_version,
        supersedes_id=artifact.supersedes_id,
    )


def build_feature_snapshot(
    instrument_id: UUID,
    evidence: Iterable[NormalizedEvidence],
    *,
    as_of: datetime,
    feature_set_version: str = "evidence-count-v1",
) -> FeatureSnapshot:
    """Build a minimal deterministic feature set without looking beyond ``as_of``."""

    snapshot_time = UtcTimestamp(as_of)
    eligible = sorted(
        (
            item
            for item in evidence
            if item.instrument_id == instrument_id
            and item.available_at.value <= snapshot_time.value
            and item.freshness_status is FreshnessStatus.FRESH
        ),
        key=lambda item: (item.available_at.value, item.content_hash),
    )
    input_hash = _canonical_hash(
        {
            "as_of": snapshot_time.value.isoformat(),
            "evidence_hashes": [item.content_hash for item in eligible],
        }
    )
    total_quality = sum((item.quality_score for item in eligible), Decimal("0"))
    values = {
        "eligible_evidence_count": str(len(eligible)),
        "eligible_quality_total": str(total_quality),
        "latest_available_at": eligible[-1].available_at.value.isoformat() if eligible else "",
    }
    return FeatureSnapshot(
        instrument_id=instrument_id,
        as_of=snapshot_time,
        feature_set_version=feature_set_version,
        values=values,
        input_hash=input_hash,
    )


def conflicting_source_locators(evidence: Iterable[NormalizedEvidence]) -> tuple[str, ...]:
    """Return sources that supplied distinct content for the same effective observation."""

    hashes_by_observation: dict[tuple[str, str, UtcTimestamp], set[str]] = {}
    for item in evidence:
        key = (item.source_name, item.source_locator, item.effective_at)
        hashes_by_observation.setdefault(key, set()).add(item.content_hash)
    return tuple(
        locator
        for (_, locator, _), hashes in sorted(
            hashes_by_observation.items(),
            key=lambda entry: (entry[0][0], entry[0][1], entry[0][2].value),
        )
        if len(hashes) > 1
    )
