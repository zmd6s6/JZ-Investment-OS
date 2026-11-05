from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from investment_os.application.monthly_review import MonthlySave, complete_months


def command(**changes):
    value = dict(
        request_id=uuid4(),
        schedule_id=uuid4(),
        expected_version=0,
        name="合成月度复核",
        mode="LOCAL_MONTHLY_REVIEW",
        frequency="MONTHLY_AFTER_COMPLETE_CALENDAR_MONTH",
        market="SSE",
        portfolio_id=uuid4(),
        portfolio_instrument_ids=[uuid4()],
        calendar_import_id=uuid4(),
        coverage_start="2026-10-01",
        coverage_end="2026-10-31",
        quote_source_name="explicit synthetic",
        evidence_source_names=[],
        valid_from="2026-10-01T00:00:00Z",
        valid_until="2026-12-01T00:00:00Z",
        retention_days=30,
        pause_method="MONTHLY_UI_PAUSE_OR_REVOKE",
        missed_run_policy="LOCAL_CURRENT_KNOWLEDGE_EXPLICIT_PERIOD",
        complete_calendar_acknowledgement=True,
        monthly_frequency_acknowledgement=True,
        scope_acknowledgement=True,
        local_only_acknowledgement=True,
        model_profile_ids=[],
        data_profile_ids=[],
        limits=dict(currency="NONE", task_tokens=0, day_tokens=0, task_cost="0", day_cost="0"),
    )
    return MonthlySave.model_validate(value | changes)


def test_monthly_requires_distinct_frequency_consent_and_explicit_zero_costs():
    value = command()
    assert value.frequency == "MONTHLY_AFTER_COMPLETE_CALENDAR_MONTH"
    readonly = value.local_read_scope()
    assert readonly.model_profiles == {} and readonly.data_profile_ids == ()
    assert not readonly.model_egress_acknowledgement
    assert not readonly.cost_acknowledgement


@pytest.mark.parametrize(
    "changes",
    [
        {"frequency": "DAILY_AFTER_EXPLICIT_CLOSE"},
        {"monthly_frequency_acknowledgement": False},
        {"complete_calendar_acknowledgement": False},
        {"data_profile_ids": [uuid4()]},
        {"model_profile_ids": [uuid4()]},
        {"mode": "SCHEDULED_SHADOW"},
        {"coverage_start": "2026-10-02"},
        {"coverage_end": "2026-10-30"},
        {"valid_until": "2026-10-01T00:00:00Z"},
        {"coverage_start": "2025-01-01"},
        {"limits": dict(currency="CNY", task_tokens=0, day_tokens=0, task_cost="0", day_cost="0")},
    ],
)
def test_daily_consent_partial_month_paid_or_missing_monthly_permission_is_rejected(changes):
    with pytest.raises(ValidationError):
        command(**changes)


def test_month_end_does_not_fire_before_market_timezone_natural_month_completion():
    start, end = date(2026, 10, 1), date(2026, 10, 31)
    assert complete_months(start, end, datetime(2026, 10, 31, 15, 59, 59, tzinfo=UTC), "SSE") == ()
    assert complete_months(start, end, datetime(2026, 10, 31, 16, tzinfo=UTC), "SSE") == (
        (start, end),
    )
    assert complete_months(start, end, datetime(2026, 11, 5, tzinfo=UTC), "SSE") == ((start, end),)


def test_leap_and_year_boundary_months_are_explicit_not_weekday_inferred():
    assert complete_months(
        date(2024, 2, 1), date(2024, 2, 29), datetime(2024, 3, 1, tzinfo=UTC), "SZSE"
    ) == ((date(2024, 2, 1), date(2024, 2, 29)),)
    assert complete_months(
        date(2026, 12, 1), date(2026, 12, 31), datetime(2026, 12, 31, 16, tzinfo=UTC), "SSE"
    ) == ((date(2026, 12, 1), date(2026, 12, 31)),)
