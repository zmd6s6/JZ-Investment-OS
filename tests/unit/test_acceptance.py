"""Delivery evidence is distinct from live health and human acceptance."""

import httpx
import pytest

from investment_os.api.app import create_app
from investment_os.application.acceptance import acceptance_snapshot


@pytest.mark.parametrize("assembled", [False, True])
def test_acceptance_never_promotes_human_acceptance_or_unshipped_paths(assembled):
    snapshot = acceptance_snapshot(
        portfolio=assembled,
        watchlist=assembled,
        providers=assembled,
        policy=assembled,
        calendar=assembled,
    )
    items = {i.key: i for i in snapshot.capabilities}
    assert snapshot.auto_trade is False and all(
        i.human_acceptance == "PENDING" for i in items.values()
    )
    assert items["portfolio"].route == ("/portfolio" if assembled else None)
    assert items["portfolio"].service == ("ASSEMBLED" if assembled else "UNAVAILABLE")
    assert items["calendar"].route == ("/calendar" if assembled else None)
    assert items["calendar"].human_acceptance == "PENDING"
    assert items["analysis"].engineering == "PARTIAL" and items["analysis"].route is None
    for key in ("decisions",):
        assert items[key].engineering == "NOT_IMPLEMENTED" and items[key].route is None
    assert items["runtime"].integration == "BASELINE_ONLY" and items["runtime"].route is None
    assert len(items) == len(snapshot.capabilities)


async def test_acceptance_http_is_read_only_and_does_not_query_database_or_provider(monkeypatch):
    app = create_app(write_api_token="synthetic-acceptance-test")

    async def fail(*args, **kwargs):
        raise AssertionError("acceptance must not query business data")

    monkeypatch.setattr("sqlalchemy.ext.asyncio.AsyncSession.execute", fail)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.get("/api/v1/product-acceptance")
        assert result.status_code == 200
        assert result.json()["evidence_basis"] == "BUILD_MANIFEST_AND_SERVICE_ASSEMBLY"
        assert (await client.post("/api/v1/product-acceptance")).status_code == 401
        assert (
            await client.post(
                "/api/v1/product-acceptance",
                headers={"Authorization": "Bearer synthetic-acceptance-test"},
            )
        ).status_code == 405
        assert all(i["human_acceptance"] == "PENDING" for i in result.json()["capabilities"])


@pytest.mark.parametrize("assembled", [False, True])
def test_trace_manifest_has_real_read_route_only_when_analysis_is_assembled(assembled):
    snapshot = acceptance_snapshot(
        portfolio=False, watchlist=False, providers=False, policy=False, analysis=assembled
    )
    item = next(value for value in snapshot.capabilities if value.key == "analysis_trace")
    assert item.work_item == "MVP-204" and item.engineering == "IMPLEMENTED"
    assert item.route == ("/analysis" if assembled else None)
    assert item.service == ("ASSEMBLED" if assembled else "UNAVAILABLE")
    assert item.human_acceptance == "PENDING"


@pytest.mark.parametrize("assembled", [False, True])
def test_candidate_research_manifest_remains_partial_and_never_accepts_checkpoint(assembled):
    snapshot = acceptance_snapshot(
        portfolio=False,
        watchlist=False,
        providers=False,
        policy=False,
        opportunities=True,
        opportunity_research=assembled,
    )
    item = next(value for value in snapshot.capabilities if value.key == "opportunities")
    assert item.engineering == "PARTIAL" and item.human_acceptance == "PENDING"
    assert ("逐个明确授权" in item.detail) is assembled
    assert ("深研 /" in item.detail) is not assembled
    assert "周定时尚未提供" in item.detail
