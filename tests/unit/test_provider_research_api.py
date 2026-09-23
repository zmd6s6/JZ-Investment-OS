from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from investment_os.api.app import create_app
from investment_os.application.provider_settings import ProviderSettingsService
from investment_os.application.research import ResearchArtifactDTO, ResearchRequest
from investment_os.domain.values import UtcTimestamp

NOW = datetime(2026, 9, 22, 9, 0, tzinfo=UTC)


class StaticRuntime:
    def __init__(self) -> None:
        self.profile_id: UUID | None = None
        self.request: ResearchRequest | None = None

    async def fetch(
        self, *, profile_id: UUID, request: ResearchRequest
    ) -> list[ResearchArtifactDTO]:
        self.profile_id = profile_id
        self.request = request
        return [
            ResearchArtifactDTO(
                provider="synthetic-provider",
                provider_ref="synthetic-ref",
                artifact_type="NEWS",
                source_name="synthetic-source",
                source_locator="https://source.example.test/item/1",
                source_tier="OTHER",
                observed_at=UtcTimestamp(NOW),
                effective_at=UtcTimestamp(NOW),
                available_at=UtcTimestamp(NOW),
                payload={"content_trust": "UNTRUSTED_SEARCH_RESULT"},
                source_schema_version="1.0",
            )
        ]


class MemoryIngestor:
    async def ingest(self, _: ResearchArtifactDTO, *, correlation_id: UUID) -> SimpleNamespace:
        assert isinstance(correlation_id, UUID)
        return SimpleNamespace(evidence_id=uuid4(), reused=False)


class FailingIngestor:
    async def ingest(self, _: ResearchArtifactDTO, *, correlation_id: UUID) -> SimpleNamespace:
        assert isinstance(correlation_id, UUID)
        raise RuntimeError("synthetic ingestion failure")


class SyncRecordingPort:
    """Minimal port slice used to verify the application's success-only sync boundary."""

    def __init__(self) -> None:
        self.syncs: list[tuple[UUID, int, int]] = []

    async def record_data_provider_sync(
        self, *, profile_id: UUID, artifact_count: int, latency_ms: int
    ) -> None:
        self.syncs.append((profile_id, artifact_count, latency_ms))


class UnusedSecretStore:
    async def put(self, _: UUID, __: str) -> None:
        raise AssertionError("fetch sync recording must not access credentials")

    async def get(self, _: UUID) -> str | None:
        raise AssertionError("fetch sync recording must not access credentials")

    async def delete(self, _: UUID) -> None:
        raise AssertionError("fetch sync recording must not access credentials")


async def test_provider_fetch_api_requires_explicit_profile_and_returns_ingest_ids() -> None:
    runtime = StaticRuntime()
    profile_id = uuid4()
    settings_port = SyncRecordingPort()
    settings_service = ProviderSettingsService(
        settings_port,
        UnusedSecretStore(),  # type: ignore[arg-type]
    )
    app = create_app(
        evidence_ingestor=MemoryIngestor(),  # type: ignore[arg-type]
        research_provider_runtime=runtime,  # type: ignore[arg-type]
        provider_settings_service=settings_service,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/research/providers/{profile_id}/fetch",
            json={
                "query": "synthetic query",
                "as_of": NOW.isoformat(),
                "instrument_ids": [],
                "max_results": 2,
            },
        )

    assert response.status_code == 200
    assert response.json()["provider_profile_id"] == str(profile_id)
    assert response.json()["results"][0]["reused"] is False
    assert runtime.profile_id == profile_id
    assert runtime.request is not None
    assert runtime.request.query == "synthetic query"
    assert runtime.request.max_results == 2
    assert len(settings_port.syncs) == 1
    recorded_profile_id, artifact_count, latency_ms = settings_port.syncs[0]
    assert recorded_profile_id == profile_id
    assert artifact_count == 1
    assert latency_ms >= 0


async def test_provider_fetch_api_does_not_record_successful_sync_when_ingestion_fails() -> None:
    runtime = StaticRuntime()
    profile_id = uuid4()
    settings_port = SyncRecordingPort()
    settings_service = ProviderSettingsService(
        settings_port,
        UnusedSecretStore(),  # type: ignore[arg-type]
    )
    app = create_app(
        evidence_ingestor=FailingIngestor(),  # type: ignore[arg-type]
        research_provider_runtime=runtime,  # type: ignore[arg-type]
        provider_settings_service=settings_service,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(RuntimeError, match="synthetic ingestion failure"):
            await client.post(
                f"/api/v1/research/providers/{profile_id}/fetch",
                json={
                    "query": "synthetic query",
                    "as_of": NOW.isoformat(),
                    "instrument_ids": [],
                    "max_results": 2,
                },
            )

    assert settings_port.syncs == []
