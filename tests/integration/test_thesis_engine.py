from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.thesis import MetricObservation
from investment_os.domain.enums import Action, ThesisState
from investment_os.domain.thesis import (
    EvidenceBackedClaim,
    InvalidationCondition,
    PillarStatus,
    ThesisChangeReason,
    ThesisContent,
    ThesisPillar,
)
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.persistence.models import (
    EvidenceRecord,
    InvestmentDecisionRecord,
    ThesisVersionEvidenceRecord,
    ThesisVersionRecord,
)
from investment_os.infrastructure.thesis_engine import (
    SqlAlchemyThesisInvalidationMonitor,
    SqlAlchemyThesisWriter,
)

NOW = datetime(2026, 9, 18, 20, 0, tzinfo=UTC)


def _content(
    evidence_ids: tuple[UUID, ...],
    *,
    summary: str = "Synthetic thesis summary",
    reverse_catalysts: bool = False,
    invalidation_window: str = "single observation",
) -> ThesisContent:
    catalysts: tuple[EvidenceBackedClaim, ...] = (
        EvidenceBackedClaim("Synthetic product adoption", (evidence_ids[0],)),
        EvidenceBackedClaim("Synthetic margin expansion", (evidence_ids[-1],)),
    )
    if reverse_catalysts:
        catalysts = tuple(reversed(catalysts))
    return ThesisContent(
        state=ThesisState.VALID,
        long_term_summary=summary,
        pillars=(
            ThesisPillar(
                key="durability",
                claim=EvidenceBackedClaim("Synthetic durable demand", (evidence_ids[0],)),
                status=PillarStatus.VALID,
            ),
        ),
        catalysts=catalysts,
        risks=(EvidenceBackedClaim("Synthetic competition", (evidence_ids[-1],)),),
        invalidation_conditions=(
            InvalidationCondition(
                condition="Synthetic retention deterioration",
                measurement="synthetic net retention",
                threshold="below 90%",
                window=invalidation_window,
            ),
        ),
        monitoring_conditions=("Review synthetic retention quarterly",),
        change_reason=ThesisChangeReason.NEW_EVIDENCE,
    )


async def _insert_instrument(database_engine: AsyncEngine, instrument_id: UUID) -> None:
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO instrument (id, symbol, exchange, asset_type, currency, lot_size, "
                "status, created_by, correlation_id) VALUES (:id, 'THESISENGINE', 'TEST', "
                "'EQUITY', 'USD', 1, 'ACTIVE', 'pytest', :correlation_id)"
            ),
            {"id": instrument_id, "correlation_id": uuid4()},
        )


async def _append_evidence(
    factory: async_sessionmaker[AsyncSession],
    *,
    instrument_id: UUID,
    available_at: datetime,
) -> UUID:
    evidence_id = uuid4()
    async with factory() as session:
        session.add(
            EvidenceRecord(
                id=evidence_id,
                instrument_id=instrument_id,
                evidence_type="EVENT",
                source_name="synthetic-provider",
                source_locator=f"synthetic://thesis/{evidence_id}",
                source_tier="PRIMARY",
                observed_at=available_at,
                effective_at=available_at,
                available_at=available_at,
                ingested_at=available_at,
                quality_score=Decimal("0.95"),
                freshness_status="FRESH",
                payload_json={"synthetic": True},
                content_hash="a" * 64,
                created_by="pytest",
                correlation_id=uuid4(),
                causation_id=None,
                metadata_json={},
            )
        )
        await session.commit()
    return evidence_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_thesis_writer_appends_material_versions_and_retains_evidence_lineage(
    database_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(database_engine, expire_on_commit=False)
    instrument_id = uuid4()
    await _insert_instrument(database_engine, instrument_id)
    first_evidence_id = await _append_evidence(
        factory, instrument_id=instrument_id, available_at=NOW - timedelta(hours=1)
    )
    second_evidence_id = await _append_evidence(
        factory, instrument_id=instrument_id, available_at=NOW - timedelta(minutes=30)
    )
    writer = SqlAlchemyThesisWriter(factory, now=lambda: NOW)

    first = await writer.write(
        instrument_id=instrument_id,
        content=_content((first_evidence_id, second_evidence_id)),
        as_of=NOW,
    )
    unchanged = await writer.write(
        instrument_id=instrument_id,
        content=_content((first_evidence_id, second_evidence_id), reverse_catalysts=True),
        as_of=NOW,
    )
    second = await writer.write(
        instrument_id=instrument_id,
        content=_content(
            (first_evidence_id, second_evidence_id), summary="Synthetic corrected summary"
        ),
        as_of=NOW,
    )
    with pytest.raises(ApplicationError) as stale_error:
        await writer.write(
            instrument_id=instrument_id,
            content=_content(
                (first_evidence_id, second_evidence_id), summary="Synthetic stale proposal"
            ),
            as_of=NOW,
            expected_current_content_hash="0" * 64,
        )

    async with factory() as session:
        versions = list(
            (
                await session.scalars(
                    select(ThesisVersionRecord)
                    .where(ThesisVersionRecord.thesis_id == first.thesis_id)
                    .order_by(ThesisVersionRecord.version)
                )
            ).all()
        )
        link_count = await session.scalar(
            select(func.count()).select_from(ThesisVersionEvidenceRecord)
        )

    assert first.created is True
    assert first.version == 1
    assert unchanged.created is False
    assert unchanged.thesis_version_id == first.thesis_version_id
    assert second.created is True
    assert second.version == 2
    assert stale_error.value.code is ApplicationErrorCode.THESIS_CURRENT_VERSION_STALE
    assert [version.parent_version_id for version in versions] == [None, first.thesis_version_id]
    assert link_count == 4


@pytest.mark.integration
@pytest.mark.asyncio
async def test_thesis_writer_rejects_missing_or_not_yet_available_evidence(
    database_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(database_engine, expire_on_commit=False)
    instrument_id = uuid4()
    await _insert_instrument(database_engine, instrument_id)
    future_evidence_id = await _append_evidence(
        factory, instrument_id=instrument_id, available_at=NOW + timedelta(minutes=1)
    )
    writer = SqlAlchemyThesisWriter(factory, now=lambda: NOW)

    with pytest.raises(ApplicationError) as error:
        await writer.write(
            instrument_id=instrument_id,
            content=_content((future_evidence_id, future_evidence_id)),
            as_of=NOW,
        )

    assert error.value.code is ApplicationErrorCode.EVIDENCE_REFERENCE_UNAVAILABLE
    missing_evidence_id = uuid4()
    with pytest.raises(ApplicationError) as missing_error:
        await writer.write(
            instrument_id=instrument_id,
            content=_content((missing_evidence_id, missing_evidence_id)),
            as_of=NOW,
        )

    assert missing_error.value.code is ApplicationErrorCode.EVIDENCE_REFERENCE_UNAVAILABLE
    async with factory() as session:
        version_count = await session.scalar(select(func.count()).select_from(ThesisVersionRecord))
    assert version_count == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_s5_invalidation_appends_broken_history_and_forced_review_candidate(
    database_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(database_engine, expire_on_commit=False)
    instrument_id = uuid4()
    await _insert_instrument(database_engine, instrument_id)
    base_evidence_id = await _append_evidence(
        factory, instrument_id=instrument_id, available_at=NOW - timedelta(hours=1)
    )
    invalidation_evidence_id = await _append_evidence(
        factory, instrument_id=instrument_id, available_at=NOW
    )
    writer = SqlAlchemyThesisWriter(factory, now=lambda: NOW)
    current_content = _content((base_evidence_id, base_evidence_id))
    initial = await writer.write(
        instrument_id=instrument_id,
        content=current_content,
        as_of=NOW,
    )
    monitor = SqlAlchemyThesisInvalidationMonitor(writer)

    result = await monitor.evaluate_and_write(
        instrument_id=instrument_id,
        current_content=current_content,
        observations=(
            MetricObservation(
                measurement="synthetic net retention",
                value=Decimal("85"),
                observed_at=UtcTimestamp(NOW),
                evidence_ids=(invalidation_evidence_id,),
            ),
        ),
        as_of=NOW,
    )

    async with factory() as session:
        versions = list(
            (
                await session.scalars(
                    select(ThesisVersionRecord)
                    .where(ThesisVersionRecord.thesis_id == initial.thesis_id)
                    .order_by(ThesisVersionRecord.version)
                )
            ).all()
        )
        decision_count = await session.scalar(
            select(func.count()).select_from(InvestmentDecisionRecord)
        )

    assert [version.thesis_state for version in versions] == ["VALID", "BROKEN"]
    assert versions[0].summary == current_content.long_term_summary
    assert versions[1].parent_version_id == initial.thesis_version_id
    assert result.thesis_write is not None
    assert result.thesis_write.created is True
    assert result.evaluation.forced_review_candidate is not None
    assert result.evaluation.forced_review_candidate.action_candidates == (
        Action.REDUCE,
        Action.EXIT,
    )
    assert decision_count == 0
