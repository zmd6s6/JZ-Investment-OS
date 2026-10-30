"""Revocation is terminal: saving a new revision cannot resurrect the same daily schedule."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from investment_os.application.daily_runtime import (
    DailyError,
    DailyMode,
    DailyPrepared,
    DailySave,
)
from investment_os.infrastructure.daily_runtime_store import (
    SqlDailyRuntimeStore,
    configuration,
)


class _RevokedSession:
    def __init__(self, version: int):
        self.record = SimpleNamespace(version=version, revoked=True)
        self.get_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def begin(self):
        return self

    async def get(self, *args, **kwargs):
        self.get_count += 1
        return self.record

    def add(self, *args, **kwargs):
        raise AssertionError("revoked schedule must not create new records")

    async def flush(self, *args, **kwargs):
        raise AssertionError("revoked schedule must not flush changes")


@pytest.mark.parametrize(
    ("expected_version", "expected_error"),
    [
        (7, "DAILY_AUTHORIZATION_REVOKED"),
        (6, "DAILY_VERSION_CONFLICT"),
    ],
)
async def test_save_cannot_resurrect_revoked_schedule(expected_version: int, expected_error: str):
    session = _RevokedSession(version=7)
    request_id, schedule_id = uuid4(), uuid4()
    command = SimpleNamespace(
        request_id=request_id,
        schedule_id=schedule_id,
        expected_version=expected_version,
        model_dump=lambda *, mode: {
            "request_id": str(request_id),
            "schedule_id": str(schedule_id),
            "expected_version": expected_version,
        },
    )
    # A legitimate caller can supply a complete prepared snapshot. Revocation
    # must be checked before its content is used or any database write occurs.
    prepared = SimpleNamespace(command=command)
    setup = SimpleNamespace(verify_profiles=AsyncMock())
    store = SqlDailyRuntimeStore(lambda: session, setup)
    store._replay = AsyncMock(return_value=None)

    with (
        patch(
            "investment_os.infrastructure.daily_runtime_store.lock", new_callable=AsyncMock
        ) as lock,
        pytest.raises(DailyError, match=expected_error),
    ):
        await store.save(prepared)

    assert session.get_count == 1
    assert lock.await_count == 2
    store._replay.assert_awaited_once()
    setup.verify_profiles.assert_not_awaited()
    assert session.record.revoked is True


@pytest.mark.parametrize("action", ["ENABLE", "PAUSE", "REVOKE"])
@pytest.mark.parametrize(
    ("expected_version", "expected_error"),
    [(7, "DAILY_AUTHORIZATION_REVOKED"), (6, "DAILY_VERSION_CONFLICT")],
)
async def test_revoked_schedule_rejects_fresh_mode_commands_without_writes(
    action: str, expected_version: int, expected_error: str
):
    session = _RevokedSession(version=7)
    setup = SimpleNamespace(verify_profiles=AsyncMock())
    store = SqlDailyRuntimeStore(lambda: session, setup)
    store._replay = AsyncMock(return_value=None)
    schedule_id = uuid4()
    command = DailyMode(
        request_id=uuid4(),
        expected_version=expected_version,
        action=action,
        confirmed=True,
    )

    with (
        patch(
            "investment_os.infrastructure.daily_runtime_store.lock", new_callable=AsyncMock
        ) as lock,
        pytest.raises(DailyError, match=expected_error),
    ):
        await store.mode(schedule_id, command)

    assert session.get_count == 1
    assert lock.await_count == 2
    store._replay.assert_awaited_once()
    setup.verify_profiles.assert_not_awaited()
    assert session.record.version == 7
    assert session.record.revoked is True


async def test_enable_expiring_during_awaited_profile_check_is_rejected_without_writes():
    """A valid initial clock check must not permit an ENABLE after its expiry."""
    session = _RevokedSession(version=7)
    session.record.revoked = False
    session.record.enabled = False
    session.record.enabled_since = None
    now = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    expiry = now + timedelta(seconds=1)
    prepared = SimpleNamespace(
        command=SimpleNamespace(valid_from=now - timedelta(days=1), valid_until=expiry),
        members=(),
        calendar_hash="a" * 64,
    )
    setup = SimpleNamespace(verify_profiles=AsyncMock())
    store = SqlDailyRuntimeStore(lambda: session, setup)
    store._replay = AsyncMock(return_value=None)
    command = DailyMode(
        request_id=uuid4(),
        expected_version=7,
        action="ENABLE",
        confirmed=True,
    )

    with (
        patch(
            "investment_os.infrastructure.daily_runtime_store.lock", new_callable=AsyncMock
        ) as lock,
        patch(
            "investment_os.infrastructure.daily_runtime_store.read_prepared",
            new_callable=AsyncMock,
            return_value=prepared,
        ),
        patch(
            "investment_os.infrastructure.daily_runtime_store.capture_scope",
            new_callable=AsyncMock,
            return_value=(),
        ),
        patch(
            "investment_os.infrastructure.daily_runtime_store.capture_calendar",
            new_callable=AsyncMock,
            return_value=(SimpleNamespace(content_hash=prepared.calendar_hash), ()),
        ),
        patch("investment_os.infrastructure.daily_runtime_store.datetime") as clock,
        patch(
            "investment_os.infrastructure.daily_runtime_store.emit", new_callable=AsyncMock
        ) as emit,
        pytest.raises(DailyError, match="DAILY_AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID"),
    ):
        clock.now.side_effect = [now, expiry]
        await store.mode(uuid4(), command)

    assert clock.now.call_count == 2
    assert lock.await_count == 2
    setup.verify_profiles.assert_awaited_once()
    emit.assert_not_awaited()
    assert session.record.enabled is False
    assert session.record.enabled_since is None
    assert session.record.version == 7


@pytest.mark.parametrize(
    ("start_offset", "end_offset", "enabled", "revoked", "expected"),
    [
        (1, 2, True, False, "DAILY_AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID"),
        (-2, 0, True, False, "DAILY_AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID"),
        (-1, 1, True, False, None),
        (-2, -1, False, False, "DAILY_PAUSED"),
        (-2, -1, False, True, "DAILY_AUTHORIZATION_REVOKED"),
    ],
)
async def test_configuration_exposes_current_time_authorization_blocker(
    start_offset: int,
    end_offset: int,
    enabled: bool,
    revoked: bool,
    expected: str | None,
):
    """Read-only UI state must not present expired enabled schedules as healthy."""
    now = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    prepared = DailyPrepared.model_construct(
        command=DailySave.model_construct(
            valid_from=now + timedelta(days=start_offset),
            valid_until=now + timedelta(days=end_offset),
        )
    )
    record = SimpleNamespace(
        id=uuid4(),
        revision_id=uuid4(),
        version=7,
        enabled=enabled,
        revoked=revoked,
        enabled_since=now - timedelta(days=1) if enabled else None,
    )
    with (
        patch(
            "investment_os.infrastructure.daily_runtime_store.read_prepared",
            new_callable=AsyncMock,
            return_value=prepared,
        ) as read,
        patch("investment_os.infrastructure.daily_runtime_store.datetime") as clock,
    ):
        clock.now.return_value = now
        result = await configuration(SimpleNamespace(), record)

    read.assert_awaited_once()
    assert result.blocker == expected
    assert result.enabled is enabled
    assert result.revoked is revoked
    assert result.auto_trade is False
