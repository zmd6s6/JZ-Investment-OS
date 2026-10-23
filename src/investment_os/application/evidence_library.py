"""Read-only, provider-neutral evidence library boundary."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EvidenceLibraryItem:
    evidence_id: UUID
    instrument_id: UUID | None
    source_name: str
    source_locator: str
    source_tier: str
    provider: str
    evidence_type: str
    title: str
    excerpt: str
    observed_at: datetime
    effective_at: datetime
    available_at: datetime
    ingested_at: datetime
    expires_at: datetime | None
    freshness_status: str
    content_hash: str


class EvidenceLibraryPort(Protocol):
    async def for_instrument(
        self, instrument_id: UUID, *, as_of: datetime, limit: int
    ) -> tuple[EvidenceLibraryItem, ...]: ...
