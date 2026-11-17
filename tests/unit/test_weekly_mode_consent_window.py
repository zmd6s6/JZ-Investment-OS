"""Consent validity fail-closed checks for the weekly mode adapter (synthetic rows)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from investment_os.infrastructure.weekly_local_mode import WeeklyModeConflict, change_weekly_mode


class FakeMappings:
    def __init__(self, row):
        self.row = row

    def one_or_none(self):
        return self.row


class FakeSession:
    def __init__(self, row):
        self.row = row
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        row = (
            self.row if len(self.calls) == 1 else {"version": 2, "enabled": True, "revoked": False}
        )
        return SimpleNamespace(mappings=lambda: FakeMappings(row))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start_delta,end_delta",
    [
        (timedelta(hours=1), timedelta(days=1)),  # not yet valid
        (timedelta(days=-2), timedelta(seconds=-1)),  # expired
        (timedelta(days=-2), timedelta(0)),  # exclusive expiry boundary
    ],
)
async def test_weekly_enable_rejects_invalid_consent_window_without_update(start_delta, end_delta):
    now = datetime(2026, 11, 16, tzinfo=UTC)
    session = FakeSession(
        {
            "version": 1,
            "enabled": False,
            "revoked": False,
            "current_revision_id": uuid4(),
            "authorization_valid_from": now + start_delta,
            "authorization_valid_until": now + end_delta,
            "database_now": now,
        }
    )
    with pytest.raises(WeeklyModeConflict, match="WEEKLY_AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID"):
        await change_weekly_mode(session, schedule_id=uuid4(), expected_version=1, action="ENABLE")
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_weekly_enable_accepts_valid_persisted_window_and_uses_db_clock():
    now = datetime(2026, 11, 16, tzinfo=UTC)
    session = FakeSession(
        {
            "version": 1,
            "enabled": False,
            "revoked": False,
            "current_revision_id": uuid4(),
            "authorization_valid_from": now,
            "authorization_valid_until": now + timedelta(days=1),
            "database_now": now,
        }
    )
    result = await change_weekly_mode(
        session, schedule_id=uuid4(), expected_version=1, action="ENABLE"
    )
    assert result.enabled and result.version == 2
    assert "clock_timestamp()" in session.calls[0][0]
    assert "weekly_local_authorization" in session.calls[0][0]
    assert len(session.calls) == 2
