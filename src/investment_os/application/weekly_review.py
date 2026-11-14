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
    persisted_watchlist_members: tuple[UUID, ...],
    calendar_coverage_attested: bool,
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
    if (
        len(set(persisted_watchlist_members)) != len(persisted_watchlist_members)
        or set(persisted_watchlist_members) != set(authorization.watchlist_instrument_ids)
    ):
        raise WeeklyReviewError("WEEKLY_WATCHLIST_MEMBERSHIP_CHANGED")
    if not calendar_coverage_attested:
        raise WeeklyReviewError("WEEKLY_CALENDAR_COVERAGE_NOT_ATTESTED")
    if len(set(calendar_sessions)) != len(calendar_sessions):
        raise WeeklyReviewError("WEEKLY_DUPLICATE_CALENDAR_SESSION")
    if any(
        session < authorization.coverage_start or session > authorization.coverage_end
        for session in calendar_sessions
    ):
        raise WeeklyReviewError("WEEKLY_CALENDAR_SESSION_OUT_OF_RANGE")
    # The caller must independently attest the complete imported calendar
    # (including closed days) against its frozen version. Session dates alone
    # are insufficient. This preflight never self-attests completeness.
    return completed_weeks(
        authorization.coverage_start,
        authorization.coverage_end,
        now,
        authorization.market,
    )


# A deterministic, immutable local report payload. This is NOT a Worker or
# historical valuation: source observations are accepted only as caller-supplied
# persisted facts and no missing historical price is inferred.
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True)
class WeeklyLocalObservation:
    instrument_id: UUID
    evidence_id: UUID | None
    observed_at: datetime | None
    price: Decimal | None
    available_at: datetime | None = None


@dataclass(frozen=True)
class WeeklyLocalReportRow:
    instrument_id: UUID
    membership: tuple[Literal["PORTFOLIO", "WATCHLIST"], ...]
    evidence_id: UUID | None
    observed_at: datetime | None
    last_known_price: Decimal | None
    price_status: Literal["SOURCE_LINKED", "UNKNOWN"]
    historical_return_status: Literal["NOT_PROVIDED"] = "NOT_PROVIDED"


@dataclass(frozen=True)
class WeeklyLocalReport:
    week_start: date
    week_end: date
    knowledge_as_of: datetime
    calendar_import_id: UUID
    rows: tuple[WeeklyLocalReportRow, ...]
    historical_holdings_status: Literal["NOT_PROVIDED"] = "NOT_PROVIDED"


def build_weekly_local_report(
    authorization: WeeklyReviewSave,
    *,
    week_start: date,
    week_end: date,
    knowledge_as_of: datetime,
    observations: tuple[WeeklyLocalObservation, ...],
) -> WeeklyLocalReport:
    """Freeze source-linked current observations; never invent week-end history.

    The production adapter must separately prove persisted calendar coverage,
    authorization and source ownership before calling this pure builder.
    """
    if knowledge_as_of.utcoffset() is None:
        raise WeeklyReviewError("WEEKLY_TIMEZONE_REQUIRED")
    if (week_start, week_end) not in completed_weeks(
        authorization.coverage_start,
        authorization.coverage_end,
        knowledge_as_of,
        authorization.market,
    ):
        raise WeeklyReviewError("WEEKLY_REPORT_WEEK_NOT_CLOSED_OR_OUT_OF_SCOPE")
    portfolio = set(authorization.portfolio_instrument_ids)
    watchlist = set(authorization.watchlist_instrument_ids)
    allowed = portfolio | watchlist
    seen: dict[UUID, WeeklyLocalObservation] = {}
    for item in observations:
        if item.instrument_id not in allowed:
            raise WeeklyReviewError("WEEKLY_REPORT_UNAUTHORIZED_INSTRUMENT")
        if item.instrument_id in seen:
            raise WeeklyReviewError("WEEKLY_REPORT_DUPLICATE_OBSERVATION")
        if item.observed_at is not None and (
            item.observed_at.utcoffset() is None
            or item.observed_at > knowledge_as_of
        ):
            raise WeeklyReviewError("WEEKLY_REPORT_INVALID_OBSERVATION_TIME")
        if item.price is not None and (
            not item.price.is_finite() or item.price <= 0
        ):
            raise WeeklyReviewError("WEEKLY_REPORT_INVALID_PRICE")
        if item.available_at is not None and (
            item.available_at.utcoffset() is None
            or item.available_at > knowledge_as_of
        ):
            raise WeeklyReviewError("WEEKLY_REPORT_INVALID_AVAILABILITY_TIME")
        if (
            item.observed_at is not None
            and item.available_at is not None
            and item.available_at < item.observed_at
        ):
            raise WeeklyReviewError("WEEKLY_REPORT_AVAILABILITY_BEFORE_OBSERVATION")
        seen[item.instrument_id] = item
    # A report cannot claim source-linked pricing without a usable, available
    # evidence reference. A future availability time is a look-ahead leak.
    # The adapter must still validate the evidence ID and source ownership.
    rows = []
    for instrument_id in sorted(allowed, key=str):
        item = seen.get(instrument_id)
        source_linked = bool(
            item is not None
            and item.evidence_id is not None
            and item.observed_at is not None
            and item.price is not None
            and item.available_at is not None
        )
        rows.append(WeeklyLocalReportRow(
            instrument_id=instrument_id,
            membership=tuple(
                role for role, members in (
                    ("PORTFOLIO", portfolio), ("WATCHLIST", watchlist)
                ) if instrument_id in members
            ),
            evidence_id=item.evidence_id if source_linked and item else None,
            observed_at=item.observed_at if source_linked and item else None,
            last_known_price=item.price if source_linked and item else None,
            price_status="SOURCE_LINKED" if source_linked else "UNKNOWN",
        ))
    return WeeklyLocalReport(
        week_start=week_start,
        week_end=week_end,
        knowledge_as_of=knowledge_as_of,
        calendar_import_id=authorization.calendar_import_id,
        rows=tuple(rows),
    )
