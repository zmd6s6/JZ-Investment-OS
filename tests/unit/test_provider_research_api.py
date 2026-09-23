from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient

from investment_os.api.app import create_app
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


async def test_provider_fetch_api_requires_explicit_profile_and_returns_ingest_ids() -> None:
    runtime = StaticRuntime()
    profile_id = uuid4()
    app = create_app(
        evidence_ingestor=MemoryIngestor(),  # type: ignore[arg-type]
        research_provider_runtime=runtime,  # type: ignore[arg-type]
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
