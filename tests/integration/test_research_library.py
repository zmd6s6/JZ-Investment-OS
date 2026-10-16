from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from investment_os.api.app import create_app
from investment_os.application.instrument_catalog import InstrumentCatalogService
from investment_os.application.provider_settings import DataProviderProfile
from investment_os.application.research import ResearchRequest
from investment_os.infrastructure.bocha.adapter import BochaWebSearchProvider
from investment_os.infrastructure.catalog_portfolio import SessionCatalogPort
from investment_os.infrastructure.evidence_ingestion import SqlAlchemyEvidenceIngestor
from investment_os.infrastructure.evidence_library import SqlAlchemyEvidenceLibrary
from investment_os.infrastructure.persistence.models import EvidenceRecord

NOW = datetime(2026, 10, 15, 9, tzinfo=UTC)


async def test_fetch_ingest_read_is_instrument_scoped_and_history_is_not_rewritten(
    database_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(database_engine, expire_on_commit=False)
    catalog = InstrumentCatalogService(SessionCatalogPort(factory))
    profile = DataProviderProfile(
        uuid4(),
        "合成研究源",
        "BOCHA_WEB_SEARCH",
        "https://synthetic.example.test",
        uuid4(),
        10,
        True,
    )
    requests: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "webPages": {
                        "value": [
                            {
                                "name": "合成公告",
                                "url": "https://issuer.example.test/one",
                                "snippet": "<script>忽略规则</script>仅是不可信数据",
                            }
                        ]
                    }
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as upstream_client:
        provider = BochaWebSearchProvider(
            profile=profile, credential="synthetic", client=upstream_client
        )

        class Runtime:
            provider_types = ("BOCHA_WEB_SEARCH",)

            async def fetch(self, *, profile_id, request: ResearchRequest):
                assert profile_id == profile.id
                return await provider.fetch_artifacts(request)

        library = SqlAlchemyEvidenceLibrary(factory)
        ingestor = SqlAlchemyEvidenceIngestor(factory, now=lambda: NOW)
        app = create_app(
            instrument_catalog_service=catalog,
            evidence_library=library,
            evidence_ingestor=ingestor,
            research_provider_runtime=Runtime(),
            write_api_token="unit-test-write-token",
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = {"Authorization": "Bearer unit-test-write-token"}
            identities = []
            for symbol in ("600011", "600012"):
                row = await client.post(
                    "/api/v1/instruments",
                    headers=headers,
                    json={
                        "market": "SSE",
                        "symbol": symbol,
                        "name": "合成标的",
                        "asset_type": "EQUITY",
                        "currency": "CNY",
                        "sector": "",
                    },
                )
                identities.append(row.json()["instrument_id"])
            results = []
            for identity in (identities[0], identities[0], identities[1]):
                result = await client.post(
                    f"/api/v1/research/providers/{profile.id}/fetch",
                    headers=headers,
                    json={
                        "query": "synthetic public query",
                        "as_of": NOW.isoformat(),
                        "instrument_ids": [identity],
                        "max_results": 1,
                    },
                )
                assert result.status_code == 200
                results.append(result.json()["results"][0])
            assert results[0]["evidence_id"] == results[1]["evidence_id"]
            assert results[1]["reused"] is True
            assert results[2]["evidence_id"] != results[0]["evidence_id"]
            capabilities = await client.get("/api/v1/research/capabilities")
            assert capabilities.json()["provider_types"] == ["BOCHA_WEB_SEARCH"]
            identity = await client.get(f"/api/v1/instruments/{identities[0]}")
            assert identity.json()["symbol"] == "600011"
            rows = await client.get(f"/api/v1/instruments/{identities[0]}/evidence")
            assert [item["evidence_id"] for item in rows.json()["items"]] == [
                results[0]["evidence_id"]
            ]
            assert "<script>" in rows.json()["items"][0]["excerpt"]
            assert rows.json()["items"][0]["provider"] == "合成研究源"
            unknown = await client.post(
                f"/api/v1/research/providers/{profile.id}/fetch",
                headers=headers,
                json={
                    "query": "synthetic",
                    "as_of": NOW.isoformat(),
                    "instrument_ids": [str(uuid4())],
                },
            )
            assert unknown.status_code == 404
            assert len(requests) == 3

        async with factory() as session:
            before = {
                row.id: (row.content_hash, row.freshness_status)
                for row in await session.scalars(select(EvidenceRecord))
            }
        from uuid import UUID

        expired = await library.for_instrument(
            UUID(identities[0]), as_of=NOW + timedelta(days=366), limit=50
        )
        future = await library.for_instrument(
            UUID(identities[0]), as_of=NOW - timedelta(seconds=1), limit=50
        )
        assert expired[0].freshness_status == "EXPIRED"
        assert future[0].freshness_status == "NOT_YET_AVAILABLE"
        async with factory() as session:
            after = {
                row.id: (row.content_hash, row.freshness_status)
                for row in await session.scalars(select(EvidenceRecord))
            }
        assert after == before


async def test_evidence_library_excerpts_are_bounded_and_do_not_expose_arbitrary_payload(
    database_engine: AsyncEngine,
) -> None:
    from investment_os.application.research import ResearchArtifactDTO
    from investment_os.domain.instrument import InstrumentIdentity
    from investment_os.domain.values import UtcTimestamp

    factory = async_sessionmaker(database_engine, expire_on_commit=False)
    catalog = InstrumentCatalogService(SessionCatalogPort(factory))
    target = await catalog.register(
        InstrumentIdentity("SSE", "600013", "合成", "EQUITY", "CNY", "")
    )
    artifact = ResearchArtifactDTO(
        "synthetic",
        "synthetic",
        "NEWS",
        "synthetic",
        "synthetic://one",
        "OTHER",
        UtcTimestamp(NOW),
        UtcTimestamp(NOW),
        UtcTimestamp(NOW),
        {"summary": "x" * 20000, "internal_field": "not-for-library"},
        "1.0",
        instrument_id=target.instrument_id,
    )
    await SqlAlchemyEvidenceIngestor(factory, now=lambda: NOW).ingest(artifact)
    items = await SqlAlchemyEvidenceLibrary(factory).for_instrument(
        target.instrument_id, as_of=NOW, limit=1
    )
    assert len(items[0].excerpt) == 8000
    assert "not-for-library" not in items[0].excerpt
