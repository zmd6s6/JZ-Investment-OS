"""Transactional persistence adapter for normalized, untrusted Evidence."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.evidence import NormalizedEvidence, normalize_artifact
from investment_os.application.research import ResearchArtifactDTO
from investment_os.infrastructure.persistence.models import EvidenceRecord, ResearchArtifactRecord
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork


@dataclass(frozen=True, slots=True)
class EvidenceIngestResult:
    evidence_id: UUID
    reused: bool


class SqlAlchemyEvidenceIngestor:
    """Persist one artifact atomically and reuse an identical immutable Evidence record."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        now: Callable[[], datetime],
    ) -> None:
        self._session_factory = session_factory
        self._now = now

    async def ingest(
        self, artifact: ResearchArtifactDTO, *, correlation_id: UUID | None = None
    ) -> EvidenceIngestResult:
        normalized = normalize_artifact(artifact, ingested_at=self._now())
        correlation = correlation_id or uuid4()
        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            existing = await uow.evidence.get_by_source_content(
                source_name=normalized.source_name,
                source_locator=normalized.source_locator,
                content_hash=normalized.content_hash,
            )
            if existing is not None:
                return EvidenceIngestResult(evidence_id=existing.id, reused=True)
            await uow.research_artifacts.append(
                ResearchArtifactRecord(
                    provider=normalized.provider,
                    provider_ref=normalized.provider_ref,
                    artifact_type=normalized.evidence_type,
                    as_of=normalized.available_at.value,
                    raw_payload_ref=normalized.source_locator,
                    normalized_payload_json=dict(normalized.payload),
                    content_hash=normalized.content_hash,
                    created_by="evidence_ingestion",
                    correlation_id=correlation,
                    causation_id=None,
                    metadata_json={"source_schema_version": normalized.source_schema_version},
                )
            )
            record = self._record(normalized, correlation)
            await uow.evidence.append(record)
            await uow.commit()
            return EvidenceIngestResult(evidence_id=record.id, reused=False)

    @staticmethod
    def _record(normalized: NormalizedEvidence, correlation_id: UUID) -> EvidenceRecord:
        return EvidenceRecord(
            instrument_id=normalized.instrument_id,
            evidence_type=normalized.evidence_type,
            source_name=normalized.source_name,
            source_locator=normalized.source_locator,
            source_tier=normalized.source_tier,
            observed_at=normalized.observed_at.value,
            effective_at=normalized.effective_at.value,
            available_at=normalized.available_at.value,
            ingested_at=normalized.ingested_at.value,
            expires_at=normalized.expires_at.value if normalized.expires_at else None,
            quality_score=normalized.quality_score,
            freshness_status=normalized.freshness_status.value,
            payload_json=dict(normalized.payload),
            content_hash=normalized.content_hash,
            supersedes_id=normalized.supersedes_id,
            created_by="evidence_ingestion",
            correlation_id=correlation_id,
            causation_id=None,
            metadata_json={
                "provider": normalized.provider,
                "provider_ref": normalized.provider_ref,
                "source_schema_version": normalized.source_schema_version,
            },
        )
