"""Actual PostgreSQL source/FK/immutability boundaries before any Decision can be proposed."""

import asyncio

import pytest
from alembic import command as migration_command
from alembic.config import Config
from analysis_decision_fixture import seed_qualification
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from investment_os.infrastructure.analysis_decision_sources import SqlDecisionQualifications
from investment_os.infrastructure.persistence.models import InvestmentDecisionRecord

pytestmark = pytest.mark.integration


async def test_qualification_reads_actual_evidence_values_relations_and_fixed_strategy(
    database_engine,
):
    ids, _numeric, qualification, strategy = await seed_qualification(database_engine)
    sessions = async_sessionmaker(database_engine, expire_on_commit=False)
    reader = SqlDecisionQualifications(sessions)
    assert await reader.get(ids["qualification"]) == qualification
    assert await reader.list(ids["portfolio"], ids["instrument"]) == (qualification,)
    async with sessions() as session:
        assert await reader.read_strategy(session, ids["strategy"]) == strategy
        assert await session.scalar(select(func.count()).select_from(InvestmentDecisionRecord)) == 0


@pytest.mark.parametrize(
    "defect", ["payload_hash", "header", "missing_relation", "fabricated_value", "evidence_hash"]
)
async def test_corrupt_or_fabricated_gate_fact_source_fails_closed(database_engine, defect):
    ids, *_ = await seed_qualification(database_engine, defect=defect)
    reader = SqlDecisionQualifications(async_sessionmaker(database_engine, expire_on_commit=False))
    with pytest.raises(ValueError, match="DECISION_QUALIFICATION_INVALID"):
        await reader.get(ids["qualification"])


@pytest.mark.parametrize(
    "table", ["analysis_decision_qualification", "analysis_decision_qualification_fact"]
)
@pytest.mark.parametrize("verb", ["UPDATE", "DELETE"])
async def test_qualification_history_rejects_update_and_delete(database_engine, table, verb):
    await seed_qualification(database_engine)
    statement = (
        f"DELETE FROM {table}"
        if verb == "DELETE"
        else (
            f"UPDATE {table} SET source_name=source_name"
            if table.endswith("qualification")
            else f"UPDATE {table} SET metric=metric"
        )
    )
    async with database_engine.begin() as connection:
        with pytest.raises(DBAPIError, match=r"append.only|immutable"):
            await connection.execute(text(statement))


async def test_nonempty_qualification_migration_refuses_destructive_downgrade(database_engine):
    ids, *_ = await seed_qualification(database_engine)
    with pytest.raises(DBAPIError, match="decision bridge history exists"):
        await asyncio.to_thread(migration_command.downgrade, Config("alembic.ini"), "20261029_0021")
    reader = SqlDecisionQualifications(async_sessionmaker(database_engine, expire_on_commit=False))
    assert (await reader.get(ids["qualification"])).qualification_id == ids["qualification"]
