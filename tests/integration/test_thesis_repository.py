from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from investment_os.infrastructure.persistence.models import (
    InvestmentThesisRecord,
    ThesisVersionRecord,
)
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork

NOW = datetime(2026, 9, 18, 18, 0, tzinfo=UTC)


def _version_record(
    *,
    thesis_id: object,
    version: int,
    created_at: datetime,
    parent_version_id: object | None = None,
) -> ThesisVersionRecord:
    return ThesisVersionRecord(
        thesis_id=thesis_id,
        version=version,
        parent_version_id=parent_version_id,
        thesis_state="VALID",
        summary=f"Synthetic Thesis version {version}",
        pillars_json=[],
        catalysts_json=[],
        risks_json=[],
        invalidation_conditions_json=[],
        monitoring_conditions_json=[],
        change_reason="NEW_EVIDENCE",
        content_hash=f"{version:x}" * 64,
        created_at=created_at,
        created_by="pytest",
        correlation_id=uuid4(),
        causation_id=None,
        metadata_json={},
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_thesis_version_repository_preserves_history_and_time_travel_reads(
    database_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(database_engine, expire_on_commit=False)
    instrument_id = uuid4()
    thesis_id = uuid4()
    correlation_id = uuid4()
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO instrument (id, symbol, exchange, asset_type, currency, lot_size, "
                "status, created_by, correlation_id) VALUES (:id, 'THESIS', 'TEST', 'EQUITY', "
                "'USD', 1, 'ACTIVE', 'pytest', :correlation_id)"
            ),
            {"id": instrument_id, "correlation_id": correlation_id},
        )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        thesis = InvestmentThesisRecord(
            id=thesis_id,
            instrument_id=instrument_id,
            status="UNKNOWN",
            current_version_id=None,
            created_by="pytest",
            correlation_id=correlation_id,
            causation_id=None,
            metadata_json={},
        )
        await uow.theses.add(thesis)
        first = _version_record(thesis_id=thesis_id, version=1, created_at=NOW - timedelta(days=1))
        await uow.thesis_versions.append(first)
        await uow.theses.update_current_version(
            thesis_id,
            expected_version=1,
            current_version_id=first.id,
            status="VALID",
        )
        second = _version_record(
            thesis_id=thesis_id,
            version=2,
            parent_version_id=first.id,
            created_at=NOW,
        )
        await uow.thesis_versions.append(second)
        await uow.theses.update_current_version(
            thesis_id,
            expected_version=2,
            current_version_id=second.id,
            status="VALID",
        )
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        history = await uow.thesis_versions.list_for_thesis(thesis_id)
        historical = await uow.thesis_versions.latest_as_of(
            thesis_id, as_of=NOW - timedelta(hours=1)
        )
        current = await uow.theses.get_by_instrument(instrument_id)
        history_versions = [record.version for record in history]
        historical_id = historical.id if historical is not None else None
        current_version_id = current.current_version_id if current is not None else None

    assert history_versions == [1, 2]
    assert historical_id == first.id
    assert current_version_id == second.id
