from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from investment_os.api.app import create_app
from investment_os.application.evidence import FeatureSnapshot, normalize_artifact
from investment_os.application.research import ResearchArtifactDTO
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.evidence_ingestion import SqlAlchemyEvidenceIngestor
from investment_os.infrastructure.feature_pipeline import SqlAlchemyFeatureSnapshotWriter
from investment_os.infrastructure.persistence.models import (
    EvidenceRecord,
    FeatureSnapshotRecord,
    ResearchArtifactRecord,
)
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
        payload = existing.payload_json if existing is not None else None

    assert existing is not None
    assert payload == {"headline": "synthetic"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingestor_reuses_identical_immutable_evidence(database_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(database_engine, expire_on_commit=False)
    ingestor = SqlAlchemyEvidenceIngestor(factory, now=lambda: NOW)
    artifact = ResearchArtifactDTO(
        provider="DSA",
        provider_ref="synthetic-evidence-dedupe",
        artifact_type="NEWS",
        source_name="synthetic-provider",
        source_locator="synthetic://evidence/dedupe",
        source_tier="PRIMARY",
        observed_at=UtcTimestamp(NOW),
        effective_at=UtcTimestamp(NOW),
        available_at=UtcTimestamp(NOW),
        payload={"headline": "synthetic"},
        source_schema_version="1.0",
    )

    first = await ingestor.ingest(artifact)
    second = await ingestor.ingest(artifact)

    assert first.reused is False
    assert second.reused is True
    assert second.evidence_id == first.evidence_id

    async with factory() as session:
        artifact_count = await session.scalar(
            select(func.count()).select_from(ResearchArtifactRecord)
        )
    assert artifact_count == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_api_persists_and_deduplicates_evidence(database_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(database_engine, expire_on_commit=False)
    app = create_app(evidence_ingestor=SqlAlchemyEvidenceIngestor(factory, now=lambda: NOW))
    payload = {
        "provider": "DSA",
        "provider_ref": "synthetic-api",
        "artifact_type": "NEWS",
        "source_name": "synthetic-provider",
        "source_locator": "synthetic://evidence/api",
        "source_tier": "PRIMARY",
        "observed_at": NOW.isoformat(),
        "effective_at": NOW.isoformat(),
        "available_at": NOW.isoformat(),
        "payload": {"headline": "synthetic"},
        "source_schema_version": "1.0",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/api/v1/research/ingest", json=payload)
        second = await client.post("/api/v1/research/ingest", json=payload)

    assert first.status_code == 200
    assert first.json()["reused"] is False
    assert second.status_code == 200
    assert second.json()["reused"] is True
    assert second.json()["evidence_id"] == first.json()["evidence_id"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_feature_snapshot_writer_persists_input_lineage(database_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(database_engine, expire_on_commit=False)
    instrument_id = uuid4()
    correlation_id = uuid4()
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO instrument (id, symbol, exchange, asset_type, currency, lot_size, "
                "status, created_by, correlation_id) VALUES (:id, 'FEATURE', 'TEST', 'EQUITY', "
                "'USD', 1, 'ACTIVE', 'pytest', :correlation_id)"
            ),
            {"id": instrument_id, "correlation_id": correlation_id},
        )
    snapshot = FeatureSnapshot(
        instrument_id=instrument_id,
        as_of=UtcTimestamp(NOW),
        feature_set_version="evidence-count-v1",
        values={"eligible_evidence_count": "0"},
        input_hash="f" * 64,
    )

    result = await SqlAlchemyFeatureSnapshotWriter(factory, now=lambda: NOW).persist(snapshot)

    async with factory() as session:
        stored = await session.get(FeatureSnapshotRecord, result.snapshot_id)
    assert stored is not None
    assert stored.input_hash == snapshot.input_hash
    assert stored.values_json == {"eligible_evidence_count": "0"}
