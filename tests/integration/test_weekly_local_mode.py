"""Transactional weekly mode CAS tests against actual PostgreSQL."""
from uuid import uuid4

import pytest
from sqlalchemy import text

from investment_os.infrastructure.weekly_local_mode import (
    WeeklyModeConflict,
    change_weekly_mode,
)

pytestmark = pytest.mark.integration


async def test_weekly_mode_rejects_enable_without_authorization(database_engine):
    from sqlalchemy.ext.asyncio import AsyncSession
    schedule_id = uuid4()
    async with AsyncSession(database_engine) as session:
        async with session.begin():
            await session.execute(text(
                "INSERT INTO weekly_local_configuration (id) VALUES (:id)"
            ), {"id": schedule_id})
            with pytest.raises(WeeklyModeConflict, match="WEEKLY_AUTHORIZATION_REQUIRED"):
                await change_weekly_mode(
                    session, schedule_id=schedule_id, expected_version=0, action="ENABLE"
                )


async def test_weekly_mode_revocation_is_terminal_and_versioned(database_engine):
    from sqlalchemy.ext.asyncio import AsyncSession
    schedule_id = uuid4()
    async with AsyncSession(database_engine) as session:
        async with session.begin():
            await session.execute(text(
                "INSERT INTO weekly_local_configuration (id) VALUES (:id)"
            ), {"id": schedule_id})
            result = await change_weekly_mode(
                session, schedule_id=schedule_id, expected_version=0, action="REVOKE"
            )
            assert (result.version, result.enabled, result.revoked) == (1, False, True)
            with pytest.raises(WeeklyModeConflict, match="WEEKLY_VERSION_CONFLICT"):
                await change_weekly_mode(
                    session, schedule_id=schedule_id, expected_version=0, action="REVOKE"
                )
            with pytest.raises(WeeklyModeConflict, match="WEEKLY_SCHEDULE_REVOKED"):
                await change_weekly_mode(
                    session, schedule_id=schedule_id, expected_version=1, action="ENABLE"
                )


async def test_weekly_mode_pause_is_not_silent_success(database_engine):
    from sqlalchemy.ext.asyncio import AsyncSession
    schedule_id = uuid4()
    async with AsyncSession(database_engine) as session:
        async with session.begin():
            await session.execute(text(
                "INSERT INTO weekly_local_configuration (id) VALUES (:id)"
            ), {"id": schedule_id})
            with pytest.raises(WeeklyModeConflict, match="WEEKLY_ALREADY_PAUSED"):
                await change_weekly_mode(
                    session, schedule_id=schedule_id, expected_version=0, action="PAUSE"
                )
            assert await session.scalar(text(
                "SELECT version FROM weekly_local_configuration WHERE id=:id"
            ), {"id": schedule_id}) == 0
