from datetime import UTC, date, datetime, time

import pytest

from investment_os.application.schedule import (
    NEW_YORK,
    ExplicitTradingCalendar,
    JobCadence,
    TradingSession,
    daily_job_for_session,
    jobs_for_session,
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


def test_planner_emits_each_cadence_only_at_known_final_market_session() -> None:
    sessions = (
        TradingSession(date(2026, 9, 28), time(16, 0)),
        TradingSession(date(2026, 9, 29), time(16, 0)),
        TradingSession(date(2026, 9, 30), time(16, 0)),
    )
    calendar = ExplicitTradingCalendar(sessions)

    early_jobs = jobs_for_session(calendar=calendar, session=sessions[0])
    final_jobs = jobs_for_session(calendar=calendar, session=sessions[-1])

    assert [job.cadence for job in early_jobs] == [JobCadence.DAILY]
    assert [job.cadence for job in final_jobs] == [
        JobCadence.DAILY,
        JobCadence.WEEKLY,
        JobCadence.MONTHLY,
        JobCadence.QUARTERLY,
    ]
    assert len({job.idempotency_key for job in final_jobs}) == 4


def test_planner_rejects_session_absent_from_calendar() -> None:
    calendar = ExplicitTradingCalendar((TradingSession(date(2026, 9, 30), time(16, 0)),))

    with pytest.raises(ValueError, match="present"):
        jobs_for_session(
            calendar=calendar,
            session=TradingSession(date(2026, 10, 1), time(16, 0)),
        )
