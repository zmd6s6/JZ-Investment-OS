from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from investment_os.application.opportunity_schedule import (
    WeeklyMode,
    WeeklySave,
    covered_weeks,
    week_due,
)


def command(**changes):
    return WeeklySave.model_validate(
        {
            "request_id": uuid4(),
            "schedule_id": uuid4(),
            "expected_version": 0,
            "name": "Synthetic",
            "venue": "SSE",
            "funnel_run_id": uuid4(),
            "calendar_import_id": uuid4(),
            "coverage_start": "2026-10-19",
            "coverage_end": "2026-10-25",
            "complete_calendar_acknowledgement": True,
            "local_only_acknowledgement": True,
            **changes,
        }
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"coverage_start": "2026-10-20"},
        {"coverage_end": "2026-10-23"},
        {"coverage_end": "2027-10-24"},
        {"complete_calendar_acknowledgement": False},
        {"complete_calendar_acknowledgement": 1},
        {"local_only_acknowledgement": "true"},
        {"venue": "US_EQUITIES"},
        {"expected_version": -1},
    ],
)
def test_incomplete_week_or_implicit_authorization_rejected(changes):
    with pytest.raises(ValidationError):
        command(**changes)


def test_week_due_requires_complete_sunday_not_guessed_friday_and_uses_market_timezone():
    value = command()
    assert covered_weeks(value.coverage_start, value.coverage_end) == (date(2026, 10, 19),)
    assert week_due(date(2026, 10, 19)).astimezone(UTC) == datetime(2026, 10, 25, 16, tzinfo=UTC)


@pytest.mark.parametrize("enabled", [1, "true", None])
def test_enable_is_explicit_boolean_and_requires_fresh_local_ack(enabled):
    with pytest.raises(ValidationError):
        WeeklyMode(
            request_id=uuid4(), expected_version=1, enabled=enabled, local_only_acknowledgement=True
        )
