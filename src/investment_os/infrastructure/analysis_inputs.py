"""Resolve bounded evidence and policy inputs without exposing SQL to application code."""

import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.analysis_governance import FrozenAnalysisPolicy
from investment_os.application.analysis_inputs import SelectedAnalysisEvidence
from investment_os.application.analysis_orchestrator import AnalysisEvidenceSource
from investment_os.application.analysis_thesis import AnalysisThesisInput
from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.evidence import FreshnessStatus, derive_display_freshness
from investment_os.infrastructure.analysis_policy import SqlAnalysisPolicies
from investment_os.infrastructure.analysis_thesis import SqlAnalysisThesis
from investment_os.infrastructure.persistence.models import (
    EvidenceRecord,
)


class SqlAlchemyAnalysisInputs:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def evidence(
        self, instrument_id: UUID, *, as_of: datetime, evidence_ids: tuple[UUID, ...] | None
    ) -> tuple[SelectedAnalysisEvidence, ...]:
        if evidence_ids is not None and (
            not 1 <= len(evidence_ids) <= 50 or len(set(evidence_ids)) != len(evidence_ids)
        ):
            raise ApplicationError(
                ApplicationErrorCode.ANALYSIS_EVIDENCE_SELECTION_INVALID,
                "invalid evidence selection",
            )
        statement = select(EvidenceRecord).where(
            EvidenceRecord.instrument_id == instrument_id,
            EvidenceRecord.available_at <= as_of,
            EvidenceRecord.expires_at.is_(None) | (EvidenceRecord.expires_at > as_of),
        )
        if evidence_ids is not None:
            statement = statement.where(EvidenceRecord.id.in_(evidence_ids))
        statement = statement.order_by(EvidenceRecord.observed_at.desc(), EvidenceRecord.id).limit(
            50
        )
        async with self._sessions() as session:
            rows = list((await session.scalars(statement)).all())
        if evidence_ids is not None and (
            {row.id for row in rows} != set(evidence_ids)
            or any(
                derive_display_freshness(
                    as_of=as_of,
                    available_at=row.available_at,
                    expires_at=row.expires_at,
                    ingested_status=row.freshness_status,
                )
                != FreshnessStatus.FRESH
                for row in rows
            )
        ):
            raise ApplicationError(
                ApplicationErrorCode.ANALYSIS_EVIDENCE_SELECTION_INVALID,
                "selected evidence unavailable",
            )
        return tuple(self._item(row) for row in rows)

    @staticmethod
    def _item(row: EvidenceRecord) -> SelectedAnalysisEvidence:
        payload = row.payload_json
        summary = next(
            (
                payload[key].strip()[:300]
                for key in ("headline", "title", "summary", "text", "content")
                if isinstance(payload.get(key), str) and payload[key].strip()
            ),
            row.source_locator[:300],
        )
        return SelectedAnalysisEvidence(
            AnalysisEvidenceSource(
                evidence_id=row.id,
                content_hash=row.content_hash,
                available_at=row.available_at,
                source_tier=row.source_tier,
                summary=summary,
                payload_excerpt=json.dumps(payload, ensure_ascii=False, default=str)[:1500],
            ),
            {
                "evidence_id": str(row.id),
                "content_hash": row.content_hash,
                "source_name": row.source_name,
                "source_locator": row.source_locator,
                "source_tier": row.source_tier,
                "provider": row.metadata_json.get("provider"),
                "observed_at": row.observed_at.isoformat(),
                "effective_at": row.effective_at.isoformat(),
                "available_at": row.available_at.isoformat(),
                "ingested_at": row.ingested_at.isoformat(),
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                "summary": summary,
                "ingested_freshness_status": row.freshness_status,
            },
        )

    async def policy(self, portfolio_id: UUID | None, *, as_of: datetime) -> FrozenAnalysisPolicy:
        return await SqlAnalysisPolicies(self._sessions).policy(portfolio_id, as_of=as_of)

    async def thesis(self, instrument_id: UUID, *, as_of: datetime) -> AnalysisThesisInput:
        return await SqlAnalysisThesis(self._sessions).thesis(instrument_id, as_of=as_of)
