"""Read-only weekly history contract tests; no PostgreSQL integration claimed."""
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from investment_os.infrastructure.weekly_report_history import (
    WeeklyHistoryError, get_weekly_report, list_weekly_reports,
)


class FakeMappings:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def one_or_none(self):
        return self.rows[0] if self.rows else None


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return SimpleNamespace(mappings=lambda: FakeMappings(self.rows))


@pytest.mark.asyncio
async def test_weekly_history_lists_scoped_stable_bounded_records():
    schedule = uuid4()
    record = dict(id=uuid4(), schedule_id=schedule, week_start=date(2026, 11, 2),
                  week_end=date(2026, 11, 8),
                  recorded_at=datetime(2026, 11, 9, tzinfo=timezone.utc),
                  content_hash="a" * 64)
    session = FakeSession([record])
    result = await list_weekly_reports(session, schedule_id=schedule, limit=5, offset=2)
    assert result[0].id == record["id"]
    sql, params = session.calls[0]
    assert "ORDER BY week_start DESC, id DESC" in sql
    assert params == {"schedule_id": schedule, "limit": 5, "offset": 2}


@pytest.mark.asyncio
@pytest.mark.parametrize("limit,offset", [(0, 0), (101, 0), (1, -1), (1, 10001)])
async def test_weekly_history_rejects_invalid_pages_without_database_access(limit, offset):
    session = FakeSession([])
    with pytest.raises(WeeklyHistoryError, match="WEEKLY_HISTORY_INVALID_PAGE"):
        await list_weekly_reports(session, schedule_id=uuid4(), limit=limit, offset=offset)
    assert session.calls == []


@pytest.mark.asyncio
async def test_weekly_history_exact_read_preserves_original_report():
    schedule, report = uuid4(), uuid4()
    row = {"id": report, "schedule_id": schedule, "report_json": {"status": "UNKNOWN"}}
    session = FakeSession([row])
    assert (await get_weekly_report(session, schedule_id=schedule, report_id=report)) == row
    sql, params = session.calls[0]
    assert "id = :report_id AND schedule_id = :schedule_id" in sql
    assert params == {"schedule_id": schedule, "report_id": report}


@pytest.mark.asyncio
async def test_weekly_history_missing_exact_report_fails_without_fallback():
    with pytest.raises(WeeklyHistoryError, match="WEEKLY_REPORT_NOT_FOUND"):
        await get_weekly_report(FakeSession([]), schedule_id=uuid4(), report_id=uuid4())
