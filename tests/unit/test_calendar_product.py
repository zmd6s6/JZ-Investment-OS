"""Explicit dates, source confirmation and market time must never be guessed."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from investment_os.application.calendar_product import (
    CalendarInput,
    CalendarModeCommand,
    CalendarProductError,
    CalendarSessionInput,
    preview_calendar,
)
from investment_os.application.schedule import MarketVenue


def draft(csv_text="business_date,close_at\n2026-10-23,15:00", **fields):
    return CalendarInput(
        venue="SSE",
        source_name="合成日历来源",
        source_version="synthetic-v1",
        confirmed_source=True,
        csv_text=csv_text,
        **fields,
    )


def test_explicit_calendar_normalizes_and_hashes_utc_without_guessing_weekdays():
    first = preview_calendar(draft("business_date,close_at\n2026-10-25,15:00\n2026-10-23,15:00"))
    second = preview_calendar(
        draft("\ufeffbusiness_date,close_at\n2026-10-23,15:00\n2026-10-25,15:00")
    )
    assert first == second
    assert first.market_timezone == "Asia/Shanghai"
    assert first.sessions[0].close_at_utc == datetime(2026, 10, 23, 7, tzinfo=UTC)
    assert first.sessions[1].business_date == date(
        2026, 10, 25
    )  # Explicit Sunday is not inferred away.


@pytest.mark.parametrize(
    "csv_text",
    [
        "business_date,close_at",
        "wrong,close_at\n2026-10-23,15:00",
        "business_date,close_at\n2026-10-23,15:00\n2026-10-23,16:00",
        "business_date,close_at\n2026-10-23,25:00",
        "business_date,close_at\n2026-10-23",
        "business_date,close_at\n2026-10-23,15:00,extra",
        "business_date,close_at\n2026-W01-1,15:00",
        "business_date,close_at\n2026-10-23,15:00+08:00",
        "business_date,close_at\n2026-10-23,15:00\ninvalid,15:00",
    ],
)
def test_calendar_invalid_or_partial_rows_reject_whole_import(csv_text):
    with pytest.raises(CalendarProductError) as failure:
        preview_calendar(draft(csv_text))
    assert failure.value.code == "CALENDAR_INPUT_INVALID"


@pytest.mark.parametrize("day,close", [("2026-03-08", "02:30"), ("2026-11-01", "01:30")])
def test_us_calendar_rejects_nonexistent_and_ambiguous_dst_close(day, close):
    command = draft(f"business_date,close_at\n{day},{close}").model_copy(
        update={"venue": MarketVenue.US_EQUITIES}
    )
    with pytest.raises(CalendarProductError):
        preview_calendar(command)


def test_calendar_limits_and_authorization_are_explicit():
    rows = [f"{date(2026, 1, 1) + timedelta(days=i)},15:00" for i in range(1000)]
    assert (
        len(preview_calendar(draft("business_date,close_at\n" + "\n".join(rows))).sessions) == 1000
    )
    with pytest.raises(CalendarProductError):
        preview_calendar(draft("business_date,close_at\n" + "\n".join(rows) + "\n2030-01-01,15:00"))
    payload = draft().model_dump(mode="json")
    for change in (
        {"confirmed_source": False},
        {"confirmed_source": 1},
        {"confirmed_source": "true"},
        {"venue": "UNKNOWN"},
        {"market_timezone": "UTC"},
    ):
        with pytest.raises(ValidationError):
            CalendarInput.model_validate({**payload, **change})
    with pytest.raises(ValidationError):
        CalendarModeCommand(
            request_id=uuid4(), expected_version=1, enabled=True, status_only_acknowledgement=False
        )
    with pytest.raises(ValidationError):
        CalendarSessionInput(business_date=date(2026, 1, 1), close_at_utc=datetime(2026, 1, 1))
