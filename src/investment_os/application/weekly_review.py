"""Independent, zero-egress weekly local portfolio/watchlist authorization contract.

This domain-facing DTO does not enable scheduling or confer daily/monthly consent.
"""
from datetime import date, datetime, timedelta
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from investment_os.application.calendar_product import Confirmed
from investment_os.application.daily_runtime import DailyDto, DailyLimits, Text
from investment_os.application.schedule import MarketVenue


class WeeklyReviewError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class WeeklyReviewSave(DailyDto):
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID
    schedule_id: UUID
    expected_version: int = Field(strict=True, ge=0)
    name: Text
    mode: Literal["LOCAL_WEEKLY_PORTFOLIO_WATCHLIST_REVIEW"]
    frequency: Literal["WEEKLY_AFTER_COMPLETE_CALENDAR_WEEK"]
    market: Literal["SSE", "SZSE"]
    portfolio_id: UUID
    portfolio_instrument_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)
    watchlist_instrument_ids: tuple[UUID, ...] = Field(max_length=100)
    calendar_import_id: UUID
    coverage_start: date
    coverage_end: date
    quote_source_name: Text
    evidence_source_names: tuple[Text, ...] = Field(max_length=10)
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    retention_days: int = Field(strict=True, ge=1, le=3650)
    pause_method: Literal["WEEKLY_UI_PAUSE_OR_REVOKE"]
    missed_run_policy: Literal["LOCAL_CURRENT_KNOWLEDGE_EXPLICIT_WEEK"]
    complete_calendar_acknowledgement: Confirmed
    weekly_frequency_acknowledgement: Confirmed
    scope_acknowledgement: Confirmed
    local_only_acknowledgement: Confirmed
    model_profile_ids: tuple[UUID, ...]
    data_profile_ids: tuple[UUID, ...]
    limits: DailyLimits

    @model_validator(mode="after")
    def fail_closed(self) -> Self:
        if (
            self.coverage_start.weekday() != 0
            or self.coverage_end.weekday() != 6
            or self.coverage_end < self.coverage_start
            or (self.coverage_end - self.coverage_start).days > 370
        ):
            raise ValueError("WEEKLY_COMPLETE_MONDAY_SUNDAY_PERIOD_REQUIRED")
        if self.valid_until <= self.valid_from:
            raise ValueError("WEEKLY_AUTHORIZATION_TIME_INVALID")
        if len(set(self.portfolio_instrument_ids)) != len(self.portfolio_instrument_ids):
            raise ValueError("WEEKLY_DUPLICATE_PORTFOLIO_MEMBER")
        if len(set(self.watchlist_instrument_ids)) != len(self.watchlist_instrument_ids):
            raise ValueError("WEEKLY_DUPLICATE_WATCHLIST_MEMBER")
        if len(set(self.evidence_source_names)) != len(self.evidence_source_names):
            raise ValueError("WEEKLY_DUPLICATE_SOURCE")
        if (
            self.model_profile_ids
            or self.data_profile_ids
            or self.limits.currency != "NONE"
            or self.limits.task_tokens
            or self.limits.day_tokens
            or self.limits.task_cost != "0"
            or self.limits.day_cost != "0"
        ):
            raise ValueError("WEEKLY_EXTERNAL_CALLS_AND_NONZERO_BUDGET_FORBIDDEN")
        return self


def completed_weeks(
    start: date, end: date, now: datetime, market: str
) -> tuple[tuple[date, date], ...]:
    """Only fully closed Monday-Sunday weeks in the selected market timezone."""
    if now.utcoffset() is None:
        raise WeeklyReviewError("WEEKLY_TIMEZONE_REQUIRED")
    if (
        start.weekday() != 0
        or end.weekday() != 6
        or end < start
        or (end - start).days > 370
    ):
        raise WeeklyReviewError("WEEKLY_COMPLETE_PERIOD_REQUIRED")
    try:
        venue = MarketVenue(market)
        if venue not in (MarketVenue.SSE, MarketVenue.SZSE):
            raise ValueError("unsupported weekly review market")
    except ValueError as exc:
        raise WeeklyReviewError("WEEKLY_UNSUPPORTED_MARKET") from exc
    local_today = now.astimezone(venue.timezone).date()
    periods = []
    current = start
    while current <= end:
        last = current + timedelta(days=6)
        if last > end:
            raise WeeklyReviewError("WEEKLY_COMPLETE_PERIOD_REQUIRED")
        if local_today > last:
            periods.append((current, last))
        current = last + timedelta(days=1)
    return tuple(periods)


def eligible_weekly_periods(
    authorization: WeeklyReviewSave,
    now: datetime,
    *,
    enabled: bool,
    revoked: bool,
    persisted_calendar_import_id: UUID,
    persisted_members: tuple[UUID, ...],
    calendar_sessions: tuple[date, ...],
) -> tuple[tuple[date, date], ...]:
    """Fail-closed, local-only Worker preflight; never starts external work.

    A weekly report must not be scheduled from a stale consent, changed
    membership, or a partial calendar. The caller must verify the imported
    calendar's source/version and persist the report idempotently.
    """
    if now.utcoffset() is None:
        raise WeeklyReviewError("WEEKLY_TIMEZONE_REQUIRED")
    if revoked or not enabled:
        return ()
    if not (authorization.valid_from <= now < authorization.valid_until):
        return ()
    if persisted_calendar_import_id != authorization.calendar_import_id:
        raise WeeklyReviewError("WEEKLY_CALENDAR_CHANGED")
    if (
        len(set(persisted_members)) != len(persisted_members)
        or set(persisted_members) != set(authorization.portfolio_instrument_ids)
    ):
        raise WeeklyReviewError("WEEKLY_PORTFOLIO_MEMBERSHIP_CHANGED")
    if len(set(calendar_sessions)) != len(calendar_sessions):
        raise WeeklyReviewError("WEEKLY_DUPLICATE_CALENDAR_SESSION")
    if any(
        session < authorization.coverage_start or session > authorization.coverage_end
        for session in calendar_sessions
    ):
        raise WeeklyReviewError("WEEKLY_CALENDAR_SESSION_OUT_OF_RANGE")
    # Calendar coverage must be independently attested by the persistence
    # adapter. A list of sessions alone cannot prove that closed days are
    # complete, so this helper intentionally does not infer coverage.
    return completed_weeks(
        authorization.coverage_start,
        authorization.coverage_end,
        now,
        authorization.market,
    )
