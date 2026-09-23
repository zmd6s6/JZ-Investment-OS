import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from investment_os.application.provider_settings import DataProviderProfile
from investment_os.application.research import (
    ResearchProviderSchemaError,
    ResearchProviderUnavailableError,
    ResearchRequest,
)
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.bocha.adapter import (
    BochaWebSearchConnectionTester,
    BochaWebSearchProvider,
)

NOW = datetime(2026, 9, 22, 9, 0, tzinfo=UTC)


def _profile(
    *, base_url: str = "https://api.example.test/v1", retention_days: int = 365
) -> DataProviderProfile:
    return DataProviderProfile(
        id=__import__("uuid").uuid4(),
        name="博查 Web 搜索",
        provider_type="BOCHA_WEB_SEARCH",
        base_url=base_url,
        credential_ref=__import__("uuid").uuid4(),
        timeout_seconds=15,
        enabled=True,
        retention_days=retention_days,
    )


def _response() -> dict[str, object]:
    return {
        "code": 200,
        "data": {
            "webPages": {
                "value": [
                    {
                        "name": "Synthetic issuer announcement",
                        "url": "https://issuer.example.test/news/1",
                        "siteName": "Synthetic Issuer",
                        "snippet": "Untrusted search snippet",
                        "summary": "Untrusted search summary",
                        "datePublished": "2026-09-21T09:00:00+08:00",
                    }
                ]
            }
        },
    }


@pytest.mark.asyncio
async def test_bocha_adapter_maps_search_results_to_untrusted_news_artifacts() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = BochaWebSearchProvider(
            profile=_profile(), credential="synthetic-credential", client=client
        )
        artifacts = await provider.fetch_artifacts(
            ResearchRequest((), UtcTimestamp(NOW), query="synthetic query", max_results=1)
        )

    assert captured["url"] == "https://api.example.test/v1/web-search"
    assert captured["authorization"] == "Bearer synthetic-credential"
    assert captured["body"] == {"query": "synthetic query", "count": 1, "summary": True}
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.artifact_type == "NEWS"
    assert artifact.source_tier == "OTHER"
    assert artifact.source_name == "Synthetic Issuer"
    assert artifact.available_at == UtcTimestamp(NOW)
    assert artifact.expires_at == UtcTimestamp(NOW + timedelta(days=365))
    assert artifact.payload["content_trust"] == "UNTRUSTED_SEARCH_RESULT"
    assert artifact.payload["summary"] == "Untrusted search summary"


@pytest.mark.asyncio
@pytest.mark.parametrize("retention_days", [1, 3650])
async def test_bocha_adapter_maps_profile_retention_boundary_to_artifact_expiry(
    retention_days: int,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=_response()))
    ) as client:
        provider = BochaWebSearchProvider(
            profile=_profile(retention_days=retention_days),
            credential="synthetic-credential",
            client=client,
        )
        artifacts = await provider.fetch_artifacts(
            ResearchRequest((), UtcTimestamp(NOW), query="synthetic query", max_results=1)
        )

    assert artifacts[0].expires_at == UtcTimestamp(NOW + timedelta(days=retention_days))


@pytest.mark.asyncio
async def test_bocha_adapter_fails_closed_for_invalid_result_schema() -> None:
    malformed = _response()
    data = malformed["data"]
    assert isinstance(data, dict)
    pages = data["webPages"]
    assert isinstance(pages, dict)
    values = pages["value"]
    assert isinstance(values, list)
    values[0] = {"name": "missing locator"}

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=malformed))
    ) as client:
        provider = BochaWebSearchProvider(
            profile=_profile(), credential="synthetic-credential", client=client
        )
        with pytest.raises(ResearchProviderSchemaError, match="url"):
            await provider.fetch_artifacts(
                ResearchRequest((), UtcTimestamp(NOW), query="synthetic query")
            )


@pytest.mark.asyncio
async def test_bocha_adapter_fails_closed_for_upstream_auth_failure() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(401, json={"message": "denied"}))
    ) as client:
        provider = BochaWebSearchProvider(
            profile=_profile(), credential="synthetic-credential", client=client
        )
        with pytest.raises(ResearchProviderUnavailableError, match="request failed"):
            await provider.fetch_artifacts(
                ResearchRequest((), UtcTimestamp(NOW), query="synthetic query")
            )


@pytest.mark.asyncio
async def test_bocha_connection_tester_uses_fixed_harmless_query() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tester = BochaWebSearchConnectionTester(client=client)
        result = await tester.test_connection(profile=_profile(), credential="synthetic-credential")

    assert result.status == "CONNECTION_SUCCEEDED"
    assert captured["body"] == {"query": "博查 API", "count": 1, "summary": True}
