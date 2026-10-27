"""Read-only evidence picker with current business-time eligibility."""

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.analysis_choices import AnalysisEvidenceChoice
from investment_os.application.evidence import derive_display_freshness
from investment_os.infrastructure.persistence.models import EvidenceRecord


class SqlAnalysisChoices:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self._sessions = sessions

    async def list_evidence(self, instrument_id: UUID) -> tuple[AnalysisEvidenceChoice, ...]:
        now = datetime.now(UTC)
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(EvidenceRecord)
                    .where(
                        or_(
                            EvidenceRecord.instrument_id == instrument_id,
                            EvidenceRecord.instrument_id.is_(None),
                        )
                    )
                    .order_by(EvidenceRecord.ingested_at.desc(), EvidenceRecord.id)
                    .limit(100)
                )
            ).all()
        output = []
        for row in rows:
            state = derive_display_freshness(
                as_of=now,
                available_at=row.available_at,
                expires_at=row.expires_at,
                ingested_status=row.freshness_status,
            ).value
            if max(row.observed_at, row.effective_at, row.available_at, row.ingested_at) > now:
                state = "NOT_YET_AVAILABLE"
            if row.quality_score <= 0:
                state = "INVALID"
            output.append(
                AnalysisEvidenceChoice(
                    evidence_id=row.id,
                    source_name=row.source_name,
                    source_locator=row.source_locator,
                    observed_at=row.observed_at,
                    expires_at=row.expires_at,
                    freshness=state,
                    excerpt=json.dumps(row.payload_json, ensure_ascii=False)[:500],
                )
            )
        return tuple(output)
