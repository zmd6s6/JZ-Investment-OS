from datetime import UTC, datetime
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient

from investment_os.api.app import create_app
from investment_os.application.instrument_catalog import InstrumentCatalogEntry

NOW = datetime(2026, 10, 15, tzinfo=UTC)


class Library:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, int]] = []

    async def for_instrument(self, instrument_id: UUID, *, as_of: datetime, limit: int):
        assert as_of.tzinfo is not None
        self.calls.append((instrument_id, limit))
        return ()


class Catalog:
    async def search(self, query: str, *, limit: int):
        return (InstrumentCatalogEntry(uuid4(), "SSE", "600001", query, "EQUITY", "CNY", ""),)


async def test_evidence_library_api_has_bounded_reads_and_keeps_search_route_static() -> None:
    from investment_os.api.schemas import StartAnalysisRequest

    assert (
        StartAnalysisRequest(instrument_id=uuid4(), portfolio_id=uuid4(), source="RESEARCH").source
        == "RESEARCH"
    )
    library = Library()
    app = create_app(evidence_library=library, instrument_catalog_service=Catalog())
    instrument_id = uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        empty = await client.get(f"/api/v1/instruments/{instrument_id}/evidence?limit=1")
        invalid = await client.get(f"/api/v1/instruments/{instrument_id}/evidence?limit=101")
        search = await client.get("/api/v1/instruments/search?q=synthetic")
        capabilities = await client.get("/api/v1/research/capabilities")
    assert empty.status_code == 200
    assert empty.json()["schema_version"] == "1.0"
    assert empty.json()["items"] == []
    assert invalid.status_code == 422
    assert library.calls == [(instrument_id, 1)]
    assert search.status_code == 200
    assert search.json()[0]["name"] == "synthetic"
    assert capabilities.json()["provider_types"] == []
