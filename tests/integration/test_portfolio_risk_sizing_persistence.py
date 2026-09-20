"""Integration coverage for immutable PR-06 Portfolio, Risk, and sizing records."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from investment_os.infrastructure.persistence.models import (
    PortfolioSnapshotRecord,
    PositionSizingRunRecord,
    RiskAssessmentRecord,
)
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork

NOW = datetime(2026, 9, 20, 4, 0, tzinfo=UTC)
HASH = "a" * 64


def _session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed_dependencies(engine: AsyncEngine) -> dict[str, UUID]:
    ids = {
        "instrument": uuid4(),
        "policy": uuid4(),
        "policy_version": uuid4(),
        "portfolio": uuid4(),
        "committee_session": uuid4(),
        "evidence": uuid4(),
    }
    correlation_id = uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO instrument "
                "(id, symbol, exchange, asset_type, currency, lot_size, status, "
                "created_by, correlation_id) "
                "VALUES (:id, 'SYNTH', 'TEST', 'EQUITY', 'USD', 1, 'ACTIVE', "
                "'pytest', :correlation_id)"
            ),
            {"id": ids["instrument"], "correlation_id": correlation_id},
        )
        await connection.execute(
            text(
                "INSERT INTO investment_policy "
                "(id, name, status, version, created_by, correlation_id) "
                "VALUES (:id, 'synthetic-pr06-policy', 'DRAFT', 1, 'pytest', :correlation_id)"
            ),
            {"id": ids["policy"], "correlation_id": correlation_id},
        )
        await connection.execute(
            text(
                "INSERT INTO investment_policy_version "
                "(id, policy_id, version, config_json, content_hash, created_by, correlation_id) "
                "VALUES (:id, :policy_id, 1, '{}'::jsonb, :content_hash, 'pytest', "
                ":correlation_id)"
            ),
            {
                "id": ids["policy_version"],
                "policy_id": ids["policy"],
                "content_hash": HASH,
                "correlation_id": correlation_id,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO portfolio "
                "(id, base_currency, status, policy_id, created_by, correlation_id) "
                "VALUES (:id, 'USD', 'ACTIVE', :policy_id, 'pytest', :correlation_id)"
            ),
            {
                "id": ids["portfolio"],
                "policy_id": ids["policy"],
                "correlation_id": correlation_id,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO committee_session "
                "(id, instrument_id, session_type, round_count, status, input_snapshot_hash, "
                "started_at, completed_at, created_by, correlation_id) "
                "VALUES (:id, :instrument_id, 'SYNTHETIC_TEST', 2, 'COMPLETED', :content_hash, "
                ":started_at, :completed_at, 'pytest', :correlation_id)"
            ),
            {
                "id": ids["committee_session"],
                "instrument_id": ids["instrument"],
                "content_hash": HASH,
                "started_at": NOW,
                "completed_at": NOW,
                "correlation_id": correlation_id,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO evidence "
                "(id, instrument_id, evidence_type, source_name, source_locator, source_tier, "
                "observed_at, effective_at, available_at, ingested_at, quality_score, "
                "freshness_status, payload_json, content_hash, created_by, correlation_id) "
                "VALUES (:id, :instrument_id, 'SYNTHETIC', 'pytest', 'synthetic://pr06', "
                "'TEST', :observed_at, :effective_at, :available_at, :ingested_at, 1, 'FRESH', "
                "'{}'::jsonb, :content_hash, 'pytest', :correlation_id)"
            ),
            {
                "id": ids["evidence"],
                "instrument_id": ids["instrument"],
                "observed_at": NOW,
                "effective_at": NOW,
                "available_at": NOW,
                "ingested_at": NOW,
                "content_hash": HASH,
                "correlation_id": correlation_id,
            },
        )
    return ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pr06_artifacts_persist_immutably_before_any_decision(
    database_engine: AsyncEngine,
) -> None:
    ids = await _seed_dependencies(database_engine)
    correlation_id = uuid4()
    snapshot_id = uuid4()
    risk_id = uuid4()
    sizing_id = uuid4()

    async with SqlAlchemyUnitOfWork(_session_factory(database_engine)) as uow:
        await uow.portfolio_snapshots.append(
            PortfolioSnapshotRecord(
                id=snapshot_id,
                portfolio_id=ids["portfolio"],
                as_of=NOW,
                cash=Decimal("500"),
                nav=Decimal("1000"),
                gross_exposure=Decimal("0.5"),
                net_exposure=Decimal("0.5"),
                source="SYNTHETIC_TEST",
                content_hash="b" * 64,
                created_by="pytest",
                correlation_id=correlation_id,
                metadata_json={},
            )
        )
        await uow.risk_assessments.append(
            RiskAssessmentRecord(
                id=risk_id,
                session_id=ids["committee_session"],
                veto=False,
                veto_codes=[],
                hard_flags_json=[],
                soft_flags_json=[{"code": "SYNTHETIC_SOFT_RISK"}],
                expires_at=NOW + timedelta(days=1),
                content_hash="c" * 64,
                created_by="pytest",
                correlation_id=correlation_id,
                metadata_json={},
            )
        )
        await uow.risk_assessments.link_evidence(risk_id, (ids["evidence"],))
        await uow.position_sizing_runs.append(
            PositionSizingRunRecord(
                id=sizing_id,
                portfolio_id=ids["portfolio"],
                instrument_id=ids["instrument"],
                decision_id=None,
                policy_version_id=ids["policy_version"],
                input_json={
                    "pending_capacity": {
                        "instrument_weight": "0.01",
                        "sector_weight": "0.01",
                        "gross_exposure": "0.01",
                    }
                },
                formula_version="synthetic-v1",
                output_json={"delta_quantity": "1", "reason_codes": []},
                input_hash="d" * 64,
                created_by="pytest",
                correlation_id=correlation_id,
                metadata_json={},
            )
        )
        await uow.commit()

    async with _session_factory(database_engine)() as session:
        snapshot = await session.get(PortfolioSnapshotRecord, snapshot_id)
        assessment = await session.get(RiskAssessmentRecord, risk_id)
        sizing = await session.get(PositionSizingRunRecord, sizing_id)
        evidence_links = await session.scalar(
            select(text("count(*)"))
            .select_from(text("risk_assessment_evidence"))
            .where(text("risk_assessment_id = :risk_id"))
            .params(risk_id=risk_id)
        )

    assert snapshot is not None and snapshot.nav == Decimal("1000")
    assert assessment is not None and assessment.soft_flags_json == [
        {"code": "SYNTHETIC_SOFT_RISK"}
    ]
    assert sizing is not None and sizing.decision_id is None
    assert sizing.input_json["pending_capacity"]["gross_exposure"] == "0.01"
    assert evidence_links == 1

    for table_name, record_id in (
        ("portfolio_snapshot", snapshot_id),
        ("risk_assessment", risk_id),
        ("position_sizing_run", sizing_id),
    ):
        with pytest.raises(DBAPIError):
            async with database_engine.begin() as connection:
                await connection.execute(
                    text(f"UPDATE {table_name} SET content_hash = :content_hash WHERE id = :id"),
                    {"id": record_id, "content_hash": "e" * 64},
                )
