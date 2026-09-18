"""Strict mapping adapter for an untrusted DSA-compatible upstream client."""

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol
from uuid import UUID

from investment_os.application.research import ResearchArtifactDTO, ResearchRequest
from investment_os.domain.values import UtcTimestamp


class ProviderUnavailableError(RuntimeError):
    """The upstream provider did not supply a usable response."""


class ProviderSchemaError(ValueError):
    """The upstream response drifted from the explicit adapter contract."""


class DSAClient(Protocol):
    async def fetch(self, request: ResearchRequest) -> list[Mapping[str, object]]: ...


class DSAAdapter:
    """Map only the documented upstream shape to internal, versioned DTOs."""

    _REQUIRED_FIELDS = frozenset(
        {
            "provider_ref",
            "artifact_type",
            "source_name",
            "source_locator",
            "source_tier",
            "observed_at",
            "effective_at",
            "available_at",
            "payload",
            "source_schema_version",
        }
    )
    _OPTIONAL_FIELDS = frozenset({"instrument_id", "expires_at"})

    def __init__(self, client: DSAClient, *, provider_name: str = "DSA") -> None:
        self._client = client
        self._provider_name = provider_name

    async def fetch_artifacts(self, request: ResearchRequest) -> list[ResearchArtifactDTO]:
        try:
            raw_artifacts = await self._client.fetch(request)
        except (OSError, TimeoutError) as exc:
            raise ProviderUnavailableError("research provider unavailable") from exc
        return [self._map_artifact(raw) for raw in raw_artifacts]

    def _map_artifact(self, raw: Mapping[str, object]) -> ResearchArtifactDTO:
        fields = frozenset(raw)
        missing = self._REQUIRED_FIELDS - fields
        unknown = fields - self._REQUIRED_FIELDS - self._OPTIONAL_FIELDS
        if missing or unknown:
            raise ProviderSchemaError(
                f"provider schema mismatch: missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        payload = raw["payload"]
        if not isinstance(payload, Mapping):
            raise ProviderSchemaError("payload must be an object")
        instrument_id = raw.get("instrument_id")
        if instrument_id is not None and not isinstance(instrument_id, UUID):
            raise ProviderSchemaError("instrument_id must be a UUID")
        expires_at = raw.get("expires_at")
        return ResearchArtifactDTO(
            provider=self._provider_name,
            provider_ref=self._string(raw, "provider_ref"),
            artifact_type=self._string(raw, "artifact_type"),
            source_name=self._string(raw, "source_name"),
            source_locator=self._string(raw, "source_locator"),
            source_tier=self._string(raw, "source_tier"),
            observed_at=self._timestamp(raw, "observed_at"),
            effective_at=self._timestamp(raw, "effective_at"),
            available_at=self._timestamp(raw, "available_at"),
            payload=dict(payload),
            source_schema_version=self._string(raw, "source_schema_version"),
            instrument_id=instrument_id,
            expires_at=UtcTimestamp(expires_at) if isinstance(expires_at, datetime) else None,
        )

    @staticmethod
    def _string(raw: Mapping[str, object], key: str) -> str:
        value = raw[key]
        if not isinstance(value, str) or not value:
            raise ProviderSchemaError(f"{key} must be a non-empty string")
        return value

    @staticmethod
    def _timestamp(raw: Mapping[str, object], key: str) -> UtcTimestamp:
        value = raw[key]
        if not isinstance(value, datetime):
            raise ProviderSchemaError(f"{key} must be a timezone-aware datetime")
        return UtcTimestamp(value)
