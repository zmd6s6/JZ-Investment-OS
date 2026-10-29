"""Revocation is terminal: saving a new revision cannot resurrect the same daily schedule."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from investment_os.application.daily_runtime import DailyError
from investment_os.infrastructure.daily_runtime_store import SqlDailyRuntimeStore


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

    with patch(
        "investment_os.infrastructure.daily_runtime_store.lock", new_callable=AsyncMock
    ) as lock:
        with pytest.raises(DailyError, match=expected_error):
            await store.save(prepared)

    assert session.get_count == 1
    assert lock.await_count == 2
    store._replay.assert_awaited_once()
    setup.verify_profiles.assert_not_awaited()
    assert session.record.revoked is True
