"""Snapshot only provable initial states; the current pointer is not a history table."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.opportunity_lifecycle import LifecycleSnapshot
from investment_os.domain.enums import InstrumentLifecycleState
from investment_os.infrastructure.persistence.models import (
    InstrumentStateRecord,
    InvestmentDecisionRecord,
    InvestmentThesisRecord,
    ThesisVersionRecord,
)


class SqlOpportunityLifecycle:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def read_lifecycle(self, instrument_id: UUID, as_of: datetime) -> LifecycleSnapshot:
        def unknown(reason: str) -> LifecycleSnapshot:
            return LifecycleSnapshot.model_validate(
                {
                    "instrument_id": instrument_id,
                    "as_of": as_of,
                    "status": "UNKNOWN",
                    "reason": reason,
                }
            )

        async with self.sessions() as session:
            row = await session.scalar(
                select(InstrumentStateRecord).where(
                    InstrumentStateRecord.instrument_id == instrument_id
                )
            )
            if row is None:
                return unknown("STATE_NOT_PROVIDED")
            if row.version != 1:
                return unknown("STATE_HISTORY_UNAVAILABLE")
            if max(row.created_at, row.effective_at) > as_of:
                return unknown("STATE_NOT_YET_AVAILABLE")
            try:
                state = InstrumentLifecycleState(row.lifecycle_state)
                if row.thesis_version_id:
                    version = await session.get(ThesisVersionRecord, row.thesis_version_id)
                    thesis = (
                        await session.get(InvestmentThesisRecord, version.thesis_id)
                        if version
                        else None
                    )
                    if (
                        not thesis
                        or thesis.instrument_id != instrument_id
                        or version is None
                        or version.created_at > as_of
                    ):
                        return unknown("STATE_INVALID")
                if row.decision_id:
                    decision = await session.get(InvestmentDecisionRecord, row.decision_id)
                    if (
                        not decision
                        or decision.instrument_id != instrument_id
                        or decision.created_at > as_of
                    ):
                        return unknown("STATE_INVALID")
                raw = {
                    "instrument_id": instrument_id,
                    "as_of": as_of,
                    "status": "AVAILABLE",
                    "reason": "RECORDED_INITIAL_STATE",
                    "state": state,
                    "source_record_id": row.id,
                    "source_version": row.version,
                    "effective_at": row.effective_at,
                    "recorded_at": row.created_at,
                    "thesis_version_id": row.thesis_version_id,
                    "decision_id": row.decision_id,
                }
                # Construct only to calculate canonical hash; validation follows immediately.
                partial = LifecycleSnapshot.model_construct(
                    instrument_id=instrument_id,
                    as_of=as_of,
                    status="AVAILABLE",
                    reason="RECORDED_INITIAL_STATE",
                    state=state,
                    source_record_id=row.id,
                    source_version=row.version,
                    effective_at=row.effective_at,
                    recorded_at=row.created_at,
                    thesis_version_id=row.thesis_version_id,
                    decision_id=row.decision_id,
                )
                return LifecycleSnapshot.model_validate(
                    {**raw, "source_hash": partial.fingerprint()}
                )
            except (ValueError, TypeError):
                return unknown("STATE_INVALID")
