"""Bounded adapter for untrusted Bocha Web Search results."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from time import monotonic
from urllib.parse import urlparse

import httpx

from investment_os.application.provider_settings import DataProviderProfile, ProviderTestResult
from investment_os.application.research import (
    ResearchArtifactDTO,
    ResearchProviderSchemaError,
    ResearchProviderUnavailableError,
    ResearchRequest,
)
from investment_os.domain.values import UtcTimestamp

_PROVIDER_TYPE = "BOCHA_WEB_SEARCH"
_SCHEMA_VERSION = "bocha-web-search-v1"
_CONNECTION_QUERY = "博查 API"
_MAX_RESULTS = 20
_MAX_TEXT_LENGTH = 8_000


class BochaWebSearchProvider:
    """Map one explicit Web Search request to untrusted NEWS artifacts.

    Search results are discovery leads only.  Every result uses source tier OTHER;
    its title, summary and snippet are retained as untrusted payload, never treated
    as a command or a verified primary-source assertion.
    """

    def __init__(
        self,
        *,
        profile: DataProviderProfile,
        credential: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._profile = profile
        self._credential = credential
        self._client = client or httpx.AsyncClient(follow_redirects=False)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_artifacts(self, request: ResearchRequest) -> list[ResearchArtifactDTO]:
        query = self._validated_query(request.query)
        count = self._validated_count(request.max_results)
        payload = await self._search(query=query, count=count)
        observed_at = request.as_of
        return self._map_results(payload=payload, query=query, observed_at=observed_at)

    async def test_connection(self) -> ProviderTestResult:
        """Use a fixed harmless query only after the owner explicitly requests a test."""

        started = monotonic()
        try:
            payload = await self._search(query=_CONNECTION_QUERY, count=1)
            self._web_values(payload)
        except (ResearchProviderUnavailableError, ResearchProviderSchemaError):
            return ProviderTestResult(
                status="CONNECTION_FAILED",
                detail="数据提供方连接认证或响应 Schema 检查失败。详细信息已脱敏。",
            )
        return ProviderTestResult(
            status="CONNECTION_SUCCEEDED",
            detail="数据提供方连接、认证和 Web Search 响应 Schema 检查通过。",
            latency_ms=int((monotonic() - started) * 1000),
        )

    async def _search(self, *, query: str, count: int) -> Mapping[str, object]:
        self._validate_profile()
        try:
            response = await self._client.post(
                f"{self._profile.base_url}/web-search",
                headers={"Authorization": f"Bearer {self._credential}"},
                json={"query": query, "count": count, "summary": True},
                timeout=httpx.Timeout(self._profile.timeout_seconds),
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ResearchProviderUnavailableError("research provider request failed") from exc
        if not isinstance(payload, Mapping) or payload.get("code") != 200:
            raise ResearchProviderSchemaError(
                "research provider returned an invalid response schema"
            )
        self._web_values(payload)
        return payload

    def _map_results(
        self,
        *,
        payload: Mapping[str, object],
        query: str,
        observed_at: UtcTimestamp,
    ) -> list[ResearchArtifactDTO]:
        artifacts: list[ResearchArtifactDTO] = []
        for item in self._web_values(payload):
            artifacts.append(self._map_item(item=item, query=query, observed_at=observed_at))
        return artifacts

    def _map_item(
        self,
        *,
        item: Mapping[str, object],
        query: str,
        observed_at: UtcTimestamp,
    ) -> ResearchArtifactDTO:
        title = self._string(item, "name")
        locator = self._locator(item)
        published_at = self._published_at(item.get("datePublished")) or observed_at
        source_name = self._source_name(item, locator)
        provider_ref = sha256(locator.encode("utf-8")).hexdigest()[:32]
        return ResearchArtifactDTO(
            provider=self._profile.name,
            provider_ref=f"web-search:{provider_ref}",
            artifact_type="NEWS",
            source_name=source_name,
            source_locator=locator,
            source_tier="OTHER",
            observed_at=published_at,
            effective_at=published_at,
            available_at=observed_at,
            payload={
                "title": title,
                "snippet": self._text(item.get("snippet")),
                "summary": self._text(item.get("summary")),
                "query": query,
                "search_provider": _PROVIDER_TYPE,
                "published_at_supplied": item.get("datePublished") is not None,
                "content_trust": "UNTRUSTED_SEARCH_RESULT",
            },
            source_schema_version=_SCHEMA_VERSION,
            expires_at=UtcTimestamp(
                observed_at.value + timedelta(days=self._profile.retention_days)
            ),
        )

    def _validate_profile(self) -> None:
        if self._profile.provider_type != _PROVIDER_TYPE:
            raise ResearchProviderSchemaError("configured data provider type is unsupported")
        parsed = urlparse(self._profile.base_url)
        if parsed.scheme == "https" and parsed.hostname:
            return
        if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
            return
        raise ResearchProviderSchemaError(
            "data provider endpoint must use HTTPS unless it is an explicit loopback endpoint"
        )

    @staticmethod
    def _validated_query(query: str | None) -> str:
        if not isinstance(query, str) or not query.strip():
            raise ResearchProviderSchemaError("web search request requires a non-empty query")
        return query.strip()

    @staticmethod
    def _validated_count(count: int) -> int:
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= _MAX_RESULTS:
            raise ResearchProviderSchemaError("web search result count is out of bounds")
        return count

    @staticmethod
    def _web_values(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise ResearchProviderSchemaError("research provider response data must be an object")
        pages = data.get("webPages")
        if not isinstance(pages, Mapping):
            raise ResearchProviderSchemaError(
                "research provider response webPages must be an object"
            )
        values = pages.get("value")
        if not isinstance(values, list) or not all(isinstance(item, Mapping) for item in values):
            raise ResearchProviderSchemaError(
                "research provider response webPages value must be a list"
            )
        return list(values)

    @staticmethod
    def _string(item: Mapping[str, object], field: str) -> str:
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ResearchProviderSchemaError(f"research provider result {field} must be a string")
        return value.strip()

    @classmethod
    def _text(cls, value: object) -> str:
        if not isinstance(value, str):
            return ""
        return value.strip()[:_MAX_TEXT_LENGTH]

    @classmethod
    def _locator(cls, item: Mapping[str, object]) -> str:
        locator = cls._string(item, "url")
        parsed = urlparse(locator)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ResearchProviderSchemaError(
                "research provider result url must be an absolute HTTP(S) URL"
            )
        return locator

    @classmethod
    def _source_name(cls, item: Mapping[str, object], locator: str) -> str:
        supplied = item.get("siteName")
        if isinstance(supplied, str) and supplied.strip():
            return supplied.strip()
        hostname = urlparse(locator).hostname
        if hostname is None:
            raise ResearchProviderSchemaError("research provider result source host is unavailable")
        return hostname

    @staticmethod
    def _published_at(value: object) -> UtcTimestamp | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ResearchProviderSchemaError(
                "research provider result datePublished must be a string"
            )
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ResearchProviderSchemaError(
                "research provider result datePublished must be an ISO timestamp"
            ) from exc
        if parsed.tzinfo is None:
            raise ResearchProviderSchemaError(
                "research provider result datePublished must have a timezone"
            )
        return UtcTimestamp(parsed.astimezone(UTC))


class BochaWebSearchConnectionTester:
    """Settings-test bridge; actual network work occurs only on explicit API/UI action."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(follow_redirects=False)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def test_connection(
        self, *, profile: DataProviderProfile, credential: str
    ) -> ProviderTestResult:
        if profile.provider_type != _PROVIDER_TYPE:
            return ProviderTestResult(
                status="UNSUPPORTED_PROVIDER",
                detail="P4 当前仅支持 BOCHA_WEB_SEARCH 数据提供方。未发起网络请求。",
            )
        return await self.provider_for(profile, credential).test_connection()

    def provider_for(self, profile: DataProviderProfile, credential: str) -> BochaWebSearchProvider:
        """Create a runtime adapter sharing this component's managed HTTP client."""

        return BochaWebSearchProvider(profile=profile, credential=credential, client=self._client)
