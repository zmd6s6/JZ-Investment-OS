from datetime import UTC, date, datetime, time

import pytest

from investment_os.application.schedule import (
    NEW_YORK,
    ExplicitTradingCalendar,
    TradingSession,
    daily_job_for_session,
)


def test_calendar_requires_explicit_session_and_daily_job_has_utc_idempotency_key() -> None:
    session = TradingSession(date(2026, 11, 27), time(13, 0))
    calendar = ExplicitTradingCalendar((session,))
    as_of = datetime(2026, 11, 27, 12, 30, tzinfo=NEW_YORK)

    job = daily_job_for_session(name="daily-report", session=session, as_of=as_of)

    assert calendar.session_for(date(2026, 11, 27)) == session
    assert calendar.session_for(date(2026, 11, 26)) is None
    assert job.scheduled_for == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    assert job.idempotency_key == "daily-report:2026-11-27T17:30:00+00:00"


def test_calendar_rejects_duplicate_market_dates() -> None:
    session = TradingSession(date(2026, 11, 27), time(13, 0))

    with pytest.raises(ValueError, match="duplicate"):
        ExplicitTradingCalendar((session, session))


def test_daily_job_rejects_cross_session_as_of_and_naive_time() -> None:
    session = TradingSession(date(2026, 11, 27), time(13, 0))

    with pytest.raises(ValueError, match="business date"):
        daily_job_for_session(
            name="daily-report",
            session=session,
            as_of=datetime(2026, 11, 28, 12, 30, tzinfo=NEW_YORK),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        daily_job_for_session(
            name="daily-report", session=session, as_of=datetime(2026, 11, 27, 12, 30)
        )
