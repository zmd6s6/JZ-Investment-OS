"""Calendar schema can upgrade safely and refuses destructive history downgrade."""

import asyncio
from uuid import uuid4

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError
from test_calendar_product_persistence import command, setup

pytestmark = pytest.mark.integration


async def test_calendar_migration_preserves_previous_schema_data_and_guards_history(
    database_engine,
):
    await database_engine.dispose()
    config = Config("alembic.ini")
    await asyncio.to_thread(alembic_command.downgrade, config, "20260929_0014")
    instrument_id = uuid4()
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO instrument "
                "(id,symbol,exchange,name,asset_type,currency,"
                "lot_size,status,created_by,correlation_id) "
                "VALUES (:id,'629901','SSE','合成迁移标的','EQUITY','CNY',1,'ACTIVE',"
                "'synthetic',:correlation)"
            ),
            {"id": instrument_id, "correlation": uuid4()},
        )
    await database_engine.dispose()
    await asyncio.to_thread(alembic_command.upgrade, config, "head")
    async with database_engine.connect() as connection:
        assert (
            await connection.scalar(
                text("SELECT id FROM instrument WHERE id=:id"), {"id": instrument_id}
            )
            == instrument_id
        )
        tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
        assert {
            "market_calendar_import",
            "market_calendar_session",
            "market_calendar_configuration",
        } <= tables
        assert (
            await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgname IN "
                    "('trg_market_calendar_import_append_only',"
                    "'trg_market_calendar_session_append_only')"
                )
            )
            == 2
        )
    _, service = setup(database_engine)
    await service.import_calendar(command())
    await database_engine.dispose()
    with pytest.raises(DBAPIError, match="calendar history exists"):
        await asyncio.to_thread(alembic_command.downgrade, config, "20260929_0014")
    async with database_engine.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM market_calendar_import")) == 1
        assert (
            await connection.scalar(text("SELECT version_num FROM alembic_version"))
            == ScriptDirectory.from_config(config).get_current_head()
        )
