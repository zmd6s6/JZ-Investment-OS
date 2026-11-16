"""Transactional, fail-closed mode transitions for weekly local review schedules.

No scheduling, provider calls, or investment decisions occur in this adapter.
The caller must authenticate the owner and use the current persisted version.
"""
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class WeeklyModeConflict(ValueError):
    """Unknown schedule, stale version, or illegal transition."""


@dataclass(frozen=True)
class WeeklyModeState:
    schedule_id: UUID
    version: int
    enabled: bool
    revoked: bool


async def change_weekly_mode(
    session: AsyncSession,
    *,
    schedule_id: UUID,
    expected_version: int,
    action: str,
) -> WeeklyModeState:
    """CAS transition; caller owns transaction and must commit on success.

    Enable is deliberately impossible before a saved immutable authorization.
    Revoke is terminal. A successful transition increments the version once.
    This does not bypass the Worker authorization/calendar/source preflight.
    """
    if expected_version < 0 or action not in ("ENABLE", "PAUSE", "REVOKE"):
        raise WeeklyModeConflict("WEEKLY_INVALID_MODE_COMMAND")
    row = (await session.execute(
        text("""
            SELECT c.version, c.enabled, c.revoked, c.current_revision_id,
                   a.valid_from AS authorization_valid_from,
                   a.valid_until AS authorization_valid_until,
                   clock_timestamp() AS database_now
            FROM weekly_local_configuration AS c
            LEFT JOIN weekly_local_authorization AS a
              ON a.schedule_id = c.id AND a.id = c.current_revision_id
            WHERE c.id = :schedule_id
            FOR UPDATE OF c
        """),
        {"schedule_id": schedule_id},
    )).mappings().one_or_none()
    if row is None:
        raise WeeklyModeConflict("WEEKLY_SCHEDULE_NOT_FOUND")
    if row["version"] != expected_version:
        raise WeeklyModeConflict("WEEKLY_VERSION_CONFLICT")
    if row["revoked"]:
        raise WeeklyModeConflict("WEEKLY_SCHEDULE_REVOKED")
    if action == "ENABLE" and row["current_revision_id"] is None:
        raise WeeklyModeConflict("WEEKLY_AUTHORIZATION_REQUIRED")
    if action == "ENABLE" and (
        row["authorization_valid_from"] is None
        or row["authorization_valid_until"] is None
        or not (row["authorization_valid_from"] <= row["database_now"] < row["authorization_valid_until"])
    ):
        raise WeeklyModeConflict("WEEKLY_AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID")
    if action == "ENABLE" and row["enabled"]:
        raise WeeklyModeConflict("WEEKLY_ALREADY_ENABLED")
    if action == "PAUSE" and not row["enabled"]:
        raise WeeklyModeConflict("WEEKLY_ALREADY_PAUSED")
    result = (await session.execute(
        text("""
            UPDATE weekly_local_configuration
            SET version = version + 1,
                enabled = :enabled,
                revoked = :revoked
            WHERE id = :schedule_id AND version = :expected_version
            RETURNING version, enabled, revoked
        """),
        {
            "schedule_id": schedule_id,
            "expected_version": expected_version,
            "enabled": action == "ENABLE",
            "revoked": action == "REVOKE",
        },
    )).mappings().one_or_none()
    if result is None:
        raise WeeklyModeConflict("WEEKLY_VERSION_CONFLICT")
    return WeeklyModeState(
        schedule_id=schedule_id,
        version=result["version"],
        enabled=result["enabled"],
        revoked=result["revoked"],
    )
