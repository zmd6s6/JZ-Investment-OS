"""Bounded evidence reads; no provider calls or history mutations."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.evidence import derive_display_freshness
from investment_os.application.evidence_library import EvidenceLibraryItem
from investment_os.infrastructure.persistence.models import EvidenceRecord


class SqlAlchemyEvidenceLibrary:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def for_instrument(
        self, instrument_id: UUID, *, as_of: datetime, limit: int
    ) -> tuple[EvidenceLibraryItem, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(EvidenceRecord)
                .where(EvidenceRecord.instrument_id == instrument_id)
                .order_by(EvidenceRecord.ingested_at.desc(), EvidenceRecord.id.desc())
                .limit(limit)
            )
            return tuple(self._item(row, as_of) for row in rows)

    @staticmethod
    def _item(row: EvidenceRecord, as_of: datetime) -> EvidenceLibraryItem:
        payload = row.payload_json
        title = next(
            (payload[key] for key in ("title", "headline") if isinstance(payload.get(key), str)),
            "无标题资料",
        )
        excerpt = "\n\n".join(
            dict.fromkeys(
                str(payload[key])[:8000]
                for key in ("summary", "snippet", "text", "content")
                if isinstance(payload.get(key), str) and str(payload[key]).strip()
            )
        )[:16000]
        provider = row.metadata_json.get("provider", "未记录")
        return EvidenceLibraryItem(
            evidence_id=row.id,
            instrument_id=row.instrument_id,
            source_name=row.source_name,
            source_locator=row.source_locator,
            source_tier=row.source_tier,
            provider=provider if isinstance(provider, str) else "未记录",
            evidence_type=row.evidence_type,
            title=str(title)[:1000],
            excerpt=excerpt,
            observed_at=row.observed_at,
            effective_at=row.effective_at,
            available_at=row.available_at,
            ingested_at=row.ingested_at,
            expires_at=row.expires_at,
            freshness_status=derive_display_freshness(
                as_of=as_of,
                available_at=row.available_at,
                expires_at=row.expires_at,
                ingested_status=row.freshness_status,
            ).value,
            content_hash=row.content_hash,
        )
