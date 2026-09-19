"""Integration coverage for append-only Agent and committee observability."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from investment_os.infrastructure.persistence.models import (
    AgentOpinionRecord,
    AgentRunRecord,
    CommitteeMessageRecord,
    CommitteeSessionRecord,
    ConflictRecord,
)
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork

NOW = datetime(2026, 9, 19, 0, 0, tzinfo=UTC)
HASH = "a" * 64


def _session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed_instrument(engine: AsyncEngine) -> UUID:
    instrument_id = uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO instrument "
                "(id, symbol, exchange, asset_type, currency, lot_size, status, "
                "created_by, correlation_id) "
                "VALUES (:id, 'SYNTH', 'TEST', 'EQUITY', 'USD', 1, 'ACTIVE', "
                "'pytest', :correlation_id)"
            ),
            {"id": instrument_id, "correlation_id": uuid4()},
        )
    return instrument_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_and_committee_observability_is_append_only_and_sanitized(
    database_engine: AsyncEngine,
) -> None:
    instrument_id = await _seed_instrument(database_engine)
    correlation_id = uuid4()
    session_id = uuid4()
    run_id = uuid4()
    opinion_id = uuid4()
    message_id = uuid4()
    conflict_id = uuid4()
    factory = _session_factory(database_engine)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.agent_observability.append_session(
            CommitteeSessionRecord(
                id=session_id,
                instrument_id=instrument_id,
                session_type="SYNTHETIC_TEST",
                round_count=2,
                status="COMPLETED",
                input_snapshot_hash=HASH,
                started_at=NOW,
                completed_at=NOW,
                created_by="pytest",
                correlation_id=correlation_id,
                metadata_json={"protocol_version": "v1"},
            )
        )
        await uow.agent_observability.append_run(
            AgentRunRecord(
                id=run_id,
                agent_role="MACRO",
                model_provider="synthetic",
                model_name="fixture-v1",
                prompt_version="v1",
                input_snapshot_hash=HASH,
                started_at=NOW,
                ended_at=NOW,
                status="SUCCEEDED",
                token_usage_json={"input": 1, "output": 1},
                error_code=None,
                created_by="pytest",
                correlation_id=correlation_id,
                metadata_json={
                    "prompt_bundle_hash": HASH,
                    "raw_output_hashes": ["b" * 64],
                    "repair_count": 0,
                    "latency_ms": 1,
                },
            )
        )
        await uow.agent_observability.append_opinion(
            AgentOpinionRecord(
                id=opinion_id,
                agent_run_id=run_id,
                instrument_id=instrument_id,
                stance="INSUFFICIENT_DATA",
                confidence=Decimal("0"),
                time_horizon="synthetic horizon",
                observations_json=[],
                thesis_impacts_json=[],
                assumptions_json=[],
                risks_json=[],
                invalidation_conditions_json=[],
                unknowns_json=["GATEWAY_FAILURE"],
                content_hash="c" * 64,
                created_by="pytest",
                correlation_id=correlation_id,
            )
        )
        await uow.agent_observability.append_message(
            CommitteeMessageRecord(
                id=message_id,
                session_id=session_id,
                round_number=2,
                agent_role="DEVILS_ADVOCATE",
                message_type="SYNTHETIC_REBUTTAL",
                opinion_id=opinion_id,
                targets_opinion_id=None,
                payload_json={"opinion_hash": "c" * 64},
                created_by="pytest",
                correlation_id=correlation_id,
            )
        )
        await uow.agent_observability.append_conflict(
            ConflictRecord(
                id=conflict_id,
                session_id=session_id,
                conflict_type="STANCE_SPREAD",
                severity="MATERIAL",
                opinion_ids=[str(opinion_id)],
                question="Resolve the synthetic disagreement through bounded review.",
                resolution=None,
                created_by="pytest",
                correlation_id=correlation_id,
                metadata_json={"protocol_version": "v1"},
            )
        )
        await uow.commit()

    async with factory() as session:
        run = await session.get(AgentRunRecord, run_id)
        message_count = await session.scalar(
            select(func.count())
            .select_from(CommitteeMessageRecord)
            .where(CommitteeMessageRecord.session_id == session_id)
        )
        conflict = await session.get(ConflictRecord, conflict_id)

    assert run is not None
    assert run.metadata_json["raw_output_hashes"] == ["b" * 64]
    assert "raw_output" not in run.metadata_json
    assert message_count == 1
    assert conflict is not None
    assert conflict.resolution is None

    for table_name, record_id in (("agent_run", run_id), ("committee_session", session_id)):
        with pytest.raises(DBAPIError):
            async with database_engine.begin() as connection:
                await connection.execute(
                    text(f"UPDATE {table_name} SET status = 'ALTERED' WHERE id = :id"),
                    {"id": record_id},
                )
    with pytest.raises(DBAPIError):
        async with database_engine.begin() as connection:
            await connection.execute(
                text("UPDATE conflict_record SET severity = 'ALTERED' WHERE id = :id"),
                {"id": conflict_id},
            )
