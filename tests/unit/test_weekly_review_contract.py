from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from investment_os.application.weekly_review import WeeklyReviewSave, WeeklyReviewError, completed_weeks


def command(**changes):
    data = dict(
        request_id=uuid4(), schedule_id=uuid4(), expected_version=0,
        name="合成周度本地复核", mode="LOCAL_WEEKLY_PORTFOLIO_WATCHLIST_REVIEW",
        frequency="WEEKLY_AFTER_COMPLETE_CALENDAR_WEEK", market="SSE",
        portfolio_id=uuid4(), portfolio_instrument_ids=[uuid4()],
        watchlist_instrument_ids=[uuid4()], calendar_import_id=uuid4(),
        coverage_start="2026-11-09", coverage_end="2026-11-15",
        quote_source_name="synthetic local", evidence_source_names=[],
        valid_from="2026-11-01T00:00:00Z", valid_until="2026-12-01T00:00:00Z",
        retention_days=30, pause_method="WEEKLY_UI_PAUSE_OR_REVOKE",
        missed_run_policy="LOCAL_CURRENT_KNOWLEDGE_EXPLICIT_WEEK",
        complete_calendar_acknowledgement=True, weekly_frequency_acknowledgement=True,
        scope_acknowledgement=True, local_only_acknowledgement=True,
        model_profile_ids=[], data_profile_ids=[],
        limits=dict(currency="NONE", task_tokens=0, day_tokens=0, task_cost="0", day_cost="0"),
    )
    return WeeklyReviewSave.model_validate(data | changes)


def test_weekly_distinct_zero_cost_consent_normal():
    value = command()
    assert value.frequency == "WEEKLY_AFTER_COMPLETE_CALENDAR_WEEK"
    assert value.model_profile_ids == () and value.data_profile_ids == ()
    assert value.portfolio_instrument_ids != value.watchlist_instrument_ids


@pytest.mark.parametrize("changes", [
    {"coverage_start": "2026-11-10"}, {"coverage_end": "2026-11-14"},
    {"weekly_frequency_acknowledgement": False},
    {"complete_calendar_acknowledgement": False},
    {"frequency": "MONTHLY_AFTER_COMPLETE_CALENDAR_MONTH"},
    {"mode": "SCHEDULED_SHADOW"},
    {"model_profile_ids": [uuid4()]}, {"data_profile_ids": [uuid4()]},
    {"limits": dict(currency="NONE", task_tokens=1, day_tokens=0, task_cost="0", day_cost="0")},
    {"valid_until": "2026-10-01T00:00:00Z"},
])
def test_weekly_partial_period_missing_consent_or_paid_scope_fails_closed(changes):
    with pytest.raises(ValidationError):
        command(**changes)


def test_weekly_duplicate_membership_is_rejected_but_cross_list_membership_is_allowed():
    member = uuid4()
    with pytest.raises(ValidationError):
        command(portfolio_instrument_ids=[member, member])
    with pytest.raises(ValidationError):
        command(watchlist_instrument_ids=[member, member])
    assert command(portfolio_instrument_ids=[member], watchlist_instrument_ids=[member])


def test_weekly_timezone_boundary_only_after_sunday():
    start, end = date(2026, 11, 9), date(2026, 11, 15)
    assert completed_weeks(start, end, datetime(2026, 11, 15, 15, 59, tzinfo=UTC), "SSE") == ()
    assert completed_weeks(start, end, datetime(2026, 11, 15, 16, tzinfo=UTC), "SSE") == ((start, end),)


def test_weekly_multiple_weeks_and_invalid_naive_time():
    start, end = date(2026, 11, 9), date(2026, 11, 22)
    assert completed_weeks(start, end, datetime(2026, 11, 16, tzinfo=UTC), "SZSE") == ((start, date(2026, 11, 15)),)
    with pytest.raises(WeeklyReviewError, match="WEEKLY_TIMEZONE_REQUIRED"):
        completed_weeks(start, end, datetime(2026, 11, 23), "SSE")
    with pytest.raises(WeeklyReviewError, match="WEEKLY_COMPLETE_PERIOD_REQUIRED"):
        completed_weeks(start, date(2026, 11, 21), datetime(2026, 11, 23, tzinfo=UTC), "SSE")


def test_weekly_standalone_enumeration_rejects_unbounded_range():
    # The Worker helper must enforce the same limit as the save DTO, even if
    # invoked without passing through API validation.
    with pytest.raises(WeeklyReviewError, match="WEEKLY_COMPLETE_PERIOD_REQUIRED"):
        completed_weeks(
            date(2026, 11, 9), date(2028, 11, 12),
            datetime(2028, 11, 13, tzinfo=UTC), "SSE",
        )


@pytest.mark.parametrize("market", ["NYSE", "US_EQUITIES"])
def test_weekly_standalone_worker_rejects_unsupported_market(market):
    # Persisted/legacy task payloads must fail with a named weekly error even
    # when they bypass the API DTO's SSE/SZSE validation.
    with pytest.raises(WeeklyReviewError, match="WEEKLY_UNSUPPORTED_MARKET"):
        completed_weeks(
            date(2026, 11, 9), date(2026, 11, 15),
            datetime(2026, 11, 16, tzinfo=UTC), market,
        )
