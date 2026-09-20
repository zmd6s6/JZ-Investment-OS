from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from investment_os.application.schedule import ExplicitTradingCalendar, TradingSession
from investment_os.infrastructure.runtime_scheduler import (
    RuntimeScheduleRunner,
    load_synthetic_calendar,
)


def test_load_synthetic_calendar_rejects_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "calendar.json"
    path.write_text(
        '{"venue":"US_EQUITIES","sessions":[],"unexpected":"nope"}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="calendar is invalid"):
        load_synthetic_calendar(path)


def test_load_synthetic_calendar_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="calendar is unavailable"):
        load_synthetic_calendar(tmp_path / "missing.json")


@pytest.mark.asyncio
async def test_runtime_scheduler_rejects_naive_poll_time() -> None:
    calendar = ExplicitTradingCalendar(
        (TradingSession(datetime(2026, 1, 2).date(), datetime.min.time()),)
    )
    runner = RuntimeScheduleRunner(
        session_factory=cast("object", None), calendar=calendar, max_replay_sessions=1
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        await runner.dispatch_due(now=datetime(2026, 1, 2))


def test_runtime_fixture_has_explicit_utc_boundary() -> None:
    calendar = load_synthetic_calendar(Path("tests/fixtures/synthetic-runtime-calendar.json"))
    session = calendar.sessions[0]
    assert session.scheduled_for(market_timezone=calendar.timezone) == datetime(
        2026, 12, 31, 21, 0, tzinfo=UTC
    )
