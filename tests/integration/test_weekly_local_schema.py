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
        row = (
            await conn.execute(
                text(
                    "SELECT version, enabled, revoked, current_revision_id "
                    "FROM weekly_local_configuration WHERE id=:id"
                ),
                {"id": schedule_id},
            )
        ).one()
        assert row.version == 0
        assert row.enabled is False
        assert row.revoked is False
        assert row.current_revision_id is None
        assert (
            await conn.scalar(
                text("SELECT count(*) FROM weekly_local_report WHERE schedule_id=:id"),
                {"id": schedule_id},
            )
            == 0
        )


async def test_weekly_local_revoked_schedule_cannot_be_enabled(database_engine):
    async with database_engine.begin() as conn:
        schedule_id = uuid4()
        await conn.execute(
            text("INSERT INTO weekly_local_configuration (id, revoked) VALUES (:id, true)"),
            {"id": schedule_id},
        )
        with pytest.raises(DBAPIError):
            async with conn.begin_nested():
                await conn.execute(
                    text("UPDATE weekly_local_configuration SET enabled=true WHERE id=:id"),
                    {"id": schedule_id},
                )


async def test_weekly_local_report_has_db_immutability_and_idempotency_constraints(database_engine):
    async with database_engine.connect() as conn:
        constraints = (
            (
                await conn.execute(
                    text("""
            SELECT conname FROM pg_constraint
            WHERE conname IN ('uq_weekly_local_report_week',
                              'uq_weekly_local_authorization_version',
                              'ck_weekly_local_report_weekly_local_complete_week')
        """)
                )
            )
            .scalars()
            .all()
        )
        assert set(constraints) == {
            "uq_weekly_local_report_week",
            "uq_weekly_local_authorization_version",
            "ck_weekly_local_report_weekly_local_complete_week",
        }
        triggers = (
            (
                await conn.execute(
                    text("""
            SELECT tgname FROM pg_trigger WHERE NOT tgisinternal
              AND tgname LIKE 'trg_weekly_local_%_immutable'
        """)
                )
            )
            .scalars()
            .all()
        )
        assert len(triggers) == 4


async def test_weekly_report_revision_is_scoped_to_its_schedule(database_engine):
    """A report cannot reference an authorization from a different schedule."""
    async with database_engine.connect() as conn:
        row = (
            await conn.execute(
                text("""
            SELECT con.confkey, con.conkey,
                   (SELECT array_agg(att.attname ORDER BY ord)
                    FROM unnest(con.conkey) WITH ORDINALITY AS keys(attnum, ord)
                    JOIN pg_attribute att ON att.attrelid = con.conrelid
                                         AND att.attnum = keys.attnum) AS local_columns,
                   (SELECT array_agg(att.attname ORDER BY ord)
                    FROM unnest(con.confkey) WITH ORDINALITY AS keys(attnum, ord)
                    JOIN pg_attribute att ON att.attrelid = con.confrelid
                                         AND att.attnum = keys.attnum) AS remote_columns
            FROM pg_constraint con
            WHERE con.conname = 'fk_weekly_local_report_authorized_revision'
              AND con.contype = 'f'
        """)
            )
        ).one()
        assert row.local_columns == ["schedule_id", "revision_id"]
        assert row.remote_columns == ["schedule_id", "id"]


async def test_weekly_authorization_calendar_coverage_requires_monday_and_sunday(database_engine):
    """The persisted contract rejects partial calendar coverage independently of the DTO."""
    async with database_engine.connect() as conn:
        names = set(
            (
                await conn.execute(
                    text("""
            SELECT conname FROM pg_constraint
            WHERE conname IN ('ck_weekly_local_authorization_weekly_local_coverage_sta_d279',
                              'ck_weekly_local_authorization_weekly_local_coverage_ends_sunday')
        """)
                )
            )
            .scalars()
            .all()
        )
        assert names == {
            "ck_weekly_local_authorization_weekly_local_coverage_sta_d279",
            "ck_weekly_local_authorization_weekly_local_coverage_ends_sunday",
        }


async def test_weekly_report_period_must_start_monday(database_engine):
    """A six-day shifted week must not pass solely because it spans seven dates."""
    async with database_engine.connect() as conn:
        names = set(
            (
                await conn.execute(
                    text("""
            SELECT conname FROM pg_constraint
            WHERE conname IN ('ck_weekly_local_report_weekly_local_complete_week',
                              'ck_weekly_local_report_weekly_local_report_starts_monday')
        """)
                )
            )
            .scalars()
            .all()
        )
        assert names == {
            "ck_weekly_local_report_weekly_local_complete_week",
            "ck_weekly_local_report_weekly_local_report_starts_monday",
        }
