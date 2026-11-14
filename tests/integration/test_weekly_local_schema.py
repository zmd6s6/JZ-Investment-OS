"""MVP-408 PostgreSQL authorization and immutable weekly history regressions."""
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.integration


async def test_weekly_local_schema_paused_and_no_report_by_default(database_engine):
    async with database_engine.begin() as conn:
        schedule_id = uuid4()
        await conn.execute(
            text("INSERT INTO weekly_local_configuration (id) VALUES (:id)"),
            {"id": schedule_id},
        )
        row = (await conn.execute(
            text("SELECT version, enabled, revoked, current_revision_id "
                 "FROM weekly_local_configuration WHERE id=:id"),
            {"id": schedule_id},
        )).one()
        assert row.version == 0
        assert row.enabled is False
        assert row.revoked is False
        assert row.current_revision_id is None
        assert await conn.scalar(text(
            "SELECT count(*) FROM weekly_local_report WHERE schedule_id=:id"
        ), {"id": schedule_id}) == 0


async def test_weekly_local_revoked_schedule_cannot_be_enabled(database_engine):
    async with database_engine.begin() as conn:
        schedule_id = uuid4()
        await conn.execute(text(
            "INSERT INTO weekly_local_configuration (id, revoked) VALUES (:id, true)"
        ), {"id": schedule_id})
        with pytest.raises(DBAPIError):
            async with conn.begin_nested():
                await conn.execute(text(
                    "UPDATE weekly_local_configuration SET enabled=true WHERE id=:id"
                ), {"id": schedule_id})


async def test_weekly_local_report_has_db_immutability_and_idempotency_constraints(database_engine):
    async with database_engine.connect() as conn:
        constraints = (await conn.execute(text("""
            SELECT conname FROM pg_constraint
            WHERE conname IN ('uq_weekly_local_report_week',
                              'uq_weekly_local_authorization_version',
                              'weekly_local_complete_week')
        """))).scalars().all()
        assert set(constraints) == {
            "uq_weekly_local_report_week",
            "uq_weekly_local_authorization_version",
            "weekly_local_complete_week",
        }
        triggers = (await conn.execute(text("""
            SELECT tgname FROM pg_trigger WHERE NOT tgisinternal
              AND tgname LIKE 'trg_weekly_local_%_immutable'
        """))).scalars().all()
        assert len(triggers) == 4
