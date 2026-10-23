"""Resolve published Thesis lineage at the analysis time, without writing or advancing it."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.analysis_thesis import (
    AnalysisThesisInput,
    AnalysisThesisVersion,
    ThesisEvidenceInput,
)
from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.evidence import derive_display_freshness
from investment_os.domain.errors import DomainError
from investment_os.infrastructure.persistence.models import (
    EvidenceRecord,
    InvestmentThesisRecord,
    ThesisVersionEvidenceRecord,
    ThesisVersionRecord,
)
from investment_os.infrastructure.thesis_engine import thesis_content_from_record


class SqlAnalysisThesis:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def thesis(self, instrument_id: UUID, *, as_of: datetime) -> AnalysisThesisInput:
        try:
            async with self._sessions() as session:
                thesis = await session.scalar(
                    select(InvestmentThesisRecord).where(
                        InvestmentThesisRecord.instrument_id == instrument_id
                    )
                )
                if thesis is None:
                    return AnalysisThesisInput(instrument_id=instrument_id, as_of=as_of)
                current = (
                    await session.get(ThesisVersionRecord, thesis.current_version_id)
                    if thesis.current_version_id
                    else None
                )
                if current is None or current.thesis_id != thesis.id:
                    raise ValueError("invalid published Thesis pointer")
                record = await session.scalar(
                    select(ThesisVersionRecord)
                    .where(
                        ThesisVersionRecord.thesis_id == thesis.id,
                        ThesisVersionRecord.version <= current.version,
                        ThesisVersionRecord.created_at <= as_of,
                    )
                    .order_by(ThesisVersionRecord.version.desc())
                    .limit(1)
                )
                if record is None:
                    return AnalysisThesisInput(instrument_id=instrument_id, as_of=as_of)
                business_time = record.metadata_json.get("as_of")
                if business_time is not None:
                    evaluated = datetime.fromisoformat(business_time)
                    if evaluated.tzinfo is None or evaluated > as_of:
                        raise ValueError("Thesis evaluation is in the future")
                if record.parent_version_id:
                    parent = await session.get(ThesisVersionRecord, record.parent_version_id)
                    if (
                        parent is None
                        or parent.thesis_id != thesis.id
                        or parent.version != record.version - 1
                    ):
                        raise ValueError("invalid Thesis parent")
                content = thesis_content_from_record(record)
                links = tuple(
                    await session.scalars(
                        select(ThesisVersionEvidenceRecord.evidence_id).where(
                            ThesisVersionEvidenceRecord.thesis_version_id == record.id
                        )
                    )
                )
                if set(links) != set(content.evidence_ids):
                    raise ValueError("invalid Thesis evidence links")
                rows = list(
                    await session.scalars(
                        select(EvidenceRecord)
                        .where(EvidenceRecord.id.in_(links))
                        .order_by(EvidenceRecord.id)
                    )
                )
                if len(rows) != len(links) or any(
                    row.instrument_id not in (None, instrument_id) for row in rows
                ):
                    raise ValueError("unavailable or foreign Thesis evidence")
                return AnalysisThesisInput(
                    instrument_id=instrument_id,
                    as_of=as_of,
                    version=AnalysisThesisVersion(
                        id=record.id,
                        thesis_id=thesis.id,
                        version=record.version,
                        parent_version_id=record.parent_version_id,
                        created_at=record.created_at,
                        content_hash=record.content_hash,
                        content=content,
                    ),
                    evidence=tuple(
                        ThesisEvidenceInput(
                            evidence_id=row.id,
                            content_hash=row.content_hash,
                            available_at=row.available_at,
                            ingested_at=row.ingested_at,
                            expires_at=row.expires_at,
                            freshness=derive_display_freshness(
                                as_of=as_of,
                                available_at=row.available_at,
                                expires_at=row.expires_at,
                                ingested_status=row.freshness_status,
                            ).value,
                        )
                        for row in rows
                    ),
                )
        except (ValueError, TypeError, KeyError, DomainError):
            raise ApplicationError(
                ApplicationErrorCode.ANALYSIS_THESIS_INVALID,
                "Thesis lineage, content or evidence is invalid at the analysis time",
            ) from None
