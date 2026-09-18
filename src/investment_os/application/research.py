"""Versioned research-provider boundary DTOs and application port."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from investment_os.domain.values import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ResearchRequest:
    """A bounded request for upstream research artifacts."""

    instrument_ids: tuple[UUID, ...]
    as_of: UtcTimestamp


@dataclass(frozen=True, slots=True)
class ResearchArtifactDTO:
    """Internal, provider-neutral representation of untrusted research data."""

    provider: str
    provider_ref: str
    artifact_type: str
    source_name: str
    source_locator: str
    source_tier: str
    observed_at: UtcTimestamp
    effective_at: UtcTimestamp
    available_at: UtcTimestamp
    payload: Mapping[str, object]
    source_schema_version: str
    instrument_id: UUID | None = None
    expires_at: UtcTimestamp | None = None


class ResearchProviderPort(Protocol):
    """Port that prevents DSA-specific types from crossing application boundaries."""

    async def fetch_artifacts(self, request: ResearchRequest) -> list[ResearchArtifactDTO]: ...


def utc_timestamp(value: datetime) -> UtcTimestamp:
    """Keep datetime validation at the application boundary explicit."""

    return UtcTimestamp(value)
