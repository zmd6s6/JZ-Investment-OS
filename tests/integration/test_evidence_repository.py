from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from investment_os.application.evidence import normalize_artifact
from investment_os.application.research import ResearchArtifactDTO
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.persistence.models import EvidenceRecord
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_evidence_repository_persists_and_finds_content_addressed_record(
    database_engine: AsyncEngine,
) -> None:
    normalized = normalize_artifact(
        ResearchArtifactDTO(
            provider="DSA",
            provider_ref="synthetic-evidence-1",
            artifact_type="NEWS",
            source_name="synthetic-provider",
            source_locator="synthetic://evidence/1",
            source_tier="PRIMARY",
            observed_at=UtcTimestamp(NOW),
            effective_at=UtcTimestamp(NOW),
            available_at=UtcTimestamp(NOW),
            payload={"headline": "synthetic"},
            source_schema_version="1.0",
        ),
        ingested_at=NOW,
    )
    factory = async_sessionmaker(database_engine, expire_on_commit=False)
    correlation_id = uuid4()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        assert (
            await uow.evidence.get_by_source_content(
                source_name=normalized.source_name,
                source_locator=normalized.source_locator,
                content_hash=normalized.content_hash,
            )
        ) is None
        await uow.evidence.append(
            EvidenceRecord(
                evidence_type=normalized.evidence_type,
                source_name=normalized.source_name,
                source_locator=normalized.source_locator,
                source_tier=normalized.source_tier,
                observed_at=normalized.observed_at.value,
                effective_at=normalized.effective_at.value,
                available_at=normalized.available_at.value,
                ingested_at=normalized.ingested_at.value,
                quality_score=normalized.quality_score,
                freshness_status=normalized.freshness_status.value,
                payload_json=dict(normalized.payload),
                content_hash=normalized.content_hash,
                created_by="pytest",
                correlation_id=correlation_id,
                causation_id=None,
                metadata_json={},
            )
        )
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        existing = await uow.evidence.get_by_source_content(
            source_name=normalized.source_name,
            source_locator=normalized.source_locator,
            content_hash=normalized.content_hash,
        )

    assert existing is not None
    assert existing.payload_json == {"headline": "synthetic"}
