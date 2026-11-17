from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from investment_os.application.calendar_product import Confirmed
from investment_os.application.daily_runtime import (
    DailyDto,
    DailyEvidenceDiff,
    DailyLimits,
    DailyLocalInputs,
    DailyMember,
    DailyMode,
    DailySave,
    DailyTask,
    Hash,
    Text,
)
from investment_os.application.market_data import MarketDataSnapshot
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.application.schedule import MarketVenue
from investment_os.domain.valuation import PortfolioNumbers

"""Independent, zero-egress weekly local portfolio/watchlist authorization contract.

This domain-facing DTO does not enable scheduling or confer daily/monthly consent.
"""


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
    if start.weekday() != 0 or end.weekday() != 6 or end < start or (end - start).days > 370:
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
    if len(set(persisted_members)) != len(persisted_members) or set(persisted_members) != set(
        authorization.portfolio_instrument_ids
    ):
        raise WeeklyReviewError("WEEKLY_PORTFOLIO_MEMBERSHIP_CHANGED")
    if len(set(persisted_watchlist_members)) != len(persisted_watchlist_members) or set(
        persisted_watchlist_members
    ) != set(authorization.watchlist_instrument_ids):
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
            item.observed_at.utcoffset() is None or item.observed_at > knowledge_as_of
        ):
            raise WeeklyReviewError("WEEKLY_REPORT_INVALID_OBSERVATION_TIME")
        if item.price is not None and (not item.price.is_finite() or item.price <= 0):
            raise WeeklyReviewError("WEEKLY_REPORT_INVALID_PRICE")
        if item.available_at is not None and (
            item.available_at.utcoffset() is None or item.available_at > knowledge_as_of
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
        observation = seen.get(instrument_id)
        source_linked = bool(
            observation is not None
            and observation.evidence_id is not None
            and observation.observed_at is not None
            and observation.price is not None
            and observation.available_at is not None
        )
        memberships: list[Literal["PORTFOLIO", "WATCHLIST"]] = []
        if instrument_id in portfolio:
            memberships.append("PORTFOLIO")
        if instrument_id in watchlist:
            memberships.append("WATCHLIST")
        rows.append(
            WeeklyLocalReportRow(
                instrument_id=instrument_id,
                membership=tuple(memberships),
                evidence_id=observation.evidence_id if source_linked and observation else None,
                observed_at=observation.observed_at if source_linked and observation else None,
                last_known_price=observation.price if source_linked and observation else None,
                price_status="SOURCE_LINKED" if source_linked else "UNKNOWN",
            )
        )
    return WeeklyLocalReport(
        week_start=week_start,
        week_end=week_end,
        knowledge_as_of=knowledge_as_of,
        calendar_import_id=authorization.calendar_import_id,
        rows=tuple(rows),
    )


"""Independent weekly local consent and immutable portfolio review contracts."""


class WeeklyError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class WeeklySave(WeeklyReviewSave):
    # Explicit complete date manifest; persisted and checked against the imported sessions.
    calendar_days: dict[date, Literal["OPEN", "CLOSED"]]

    def local_read_scope(self) -> DailySave:
        """Adapt read-only capture, never save/enable Daily or confer model consent."""
        return DailySave(
            request_id=self.request_id,
            schedule_id=self.schedule_id,
            expected_version=self.expected_version,
            name=self.name,
            mode="LOCAL_STATUS_ONLY",
            market=self.market,
            portfolio_id=self.portfolio_id,
            portfolio_instrument_ids=self.portfolio_instrument_ids,
            watchlist_instrument_ids=self.watchlist_instrument_ids,
            calendar_import_id=self.calendar_import_id,
            coverage_start=self.coverage_start,
            coverage_end=self.coverage_end,
            frequency="DAILY_AFTER_EXPLICIT_CLOSE",
            missed_run_policy="LOCAL_REPORT_ONLY_NO_RESEARCH",
            quote_source_name=self.quote_source_name,
            evidence_source_names=self.evidence_source_names,
            retention_days=self.retention_days,
            valid_from=self.valid_from,
            valid_until=self.valid_until,
            model_profiles={},
            data_profile_ids=(),
            limits=self.limits,
            pause_method="DAILY_UI_PAUSE_OR_REVOKE",
            complete_calendar_acknowledgement=True,
            scope_acknowledgement=True,
            local_only_acknowledgement=True,
            model_egress_acknowledgement=False,
            cost_acknowledgement=False,
        )


class WeeklyPrepared(DailyDto):
    command: WeeklySave
    calendar_hash: Hash
    calendar_source: Text
    calendar_version: Text
    members: tuple[DailyMember, ...]
    prepared_at: AwareDatetime
    content_hash: Hash

    @model_validator(mode="after")
    def exact_scope(self) -> Self:
        if (
            len(self.members)
            != len(
                set(self.command.portfolio_instrument_ids)
                | set(self.command.watchlist_instrument_ids)
            )
            or {row.instrument_id for row in self.members}
            != set(self.command.portfolio_instrument_ids)
            | set(self.command.watchlist_instrument_ids)
            or any(
                row.in_portfolio != (row.instrument_id in self.command.portfolio_instrument_ids)
                or row.in_watchlist != (row.instrument_id in self.command.watchlist_instrument_ids)
                or row.market != self.command.market
                for row in self.members
            )
        ):
            raise ValueError("WEEKLY_PREPARED_SCOPE_MISMATCH")
        return self


class WeeklyConfirm(DailyDto):
    command: WeeklySave
    preview_hash: Hash


class WeeklyConfiguration(DailyDto):
    schedule_id: UUID
    revision_id: UUID | None
    version: int
    enabled: bool
    revoked: bool
    prepared: WeeklyPrepared | None
    blocker: str | None
    auto_trade: Literal[False] = False


class WeeklyReadReference(DailyDto):
    kind: Literal["THESIS", "ANALYSIS", "RISK", "DECISION"]
    record_id: UUID
    instrument_id: UUID
    recorded_at: AwareDatetime
    status: str
    evidence_ids: tuple[UUID, ...]
    content_hash: Hash
    unknowns: tuple[str, ...] = ()


class WeeklyHoldingReview(DailyDto):
    instrument_id: UUID
    symbol: str
    core_quantity: str
    tactical_quantity: str
    core_change: str | None
    tactical_change: str | None
    quote_status: str
    references: tuple[WeeklyReadReference, ...]
    reentry_assessment: Literal["NOT_PROVIDED"] = "NOT_PROVIDED"
    unknowns: tuple[str, ...]


class WeeklyReport(DailyDto):
    schema_version: Literal["1.0"] = "1.0"
    report_id: UUID
    task_run_id: UUID
    schedule_id: UUID
    revision_id: UUID
    authorization_version: int
    period_start: date
    period_end: date
    business_as_of: AwareDatetime | None
    knowledge_as_of: AwareDatetime
    recorded_at: AwareDatetime
    usable_until: AwareDatetime
    phase: Literal["LOCAL_REVIEW", "DEGRADED", "CLOSED_WEEK_SKIPPED"]
    authorization: WeeklyPrepared
    local_inputs: DailyLocalInputs | None
    evidence_diff: DailyEvidenceDiff | None
    baseline_report_id: UUID | None
    baseline_status: Literal["FIRST_RUN_NO_BASELINE", "COMPARABLE_BASELINE"]
    holdings: tuple[WeeklyHoldingReview, ...]
    valuation: PortfolioNumbers | None
    quotes: tuple[MarketDataSnapshot, ...]
    unknowns: tuple[str, ...]
    recovery: tuple[str, ...]
    content_hash: Hash
    simulation_only: Literal[True] = True
    auto_trade: Literal[False] = False

    @model_validator(mode="after")
    def exact_authorized_report(self) -> Self:
        command = self.authorization.command
        if (
            self.schedule_id != command.schedule_id
            or not command.coverage_start
            <= self.period_start
            <= self.period_end
            <= command.coverage_end
            or self.usable_until <= self.knowledge_as_of
        ):
            raise ValueError("WEEKLY_REPORT_AUTHORIZATION_OR_PERIOD_MISMATCH")
        if self.local_inputs is not None:
            inputs = self.local_inputs
            if (
                inputs.portfolio.portfolio_id != command.portfolio_id
                or inputs.members != self.authorization.members
                or {p.instrument_id for p in inputs.portfolio.positions}
                != set(command.portfolio_instrument_ids)
                or {p.instrument_id for p in self.holdings} != set(command.portfolio_instrument_ids)
                or any(
                    e.instrument_id
                    not in {*command.portfolio_instrument_ids, *command.watchlist_instrument_ids}
                    or e.source_name
                    not in {*command.evidence_source_names, command.quote_source_name}
                    for e in inputs.evidence
                )
            ):
                raise ValueError("WEEKLY_REPORT_SCOPE_OR_SOURCE_MISMATCH")
        elif (
            self.holdings
            or self.valuation is not None
            or self.quotes
            or self.evidence_diff is not None
        ):
            raise ValueError("WEEKLY_CLOSED_WEEK_HAS_UNAUTHORIZED_CONTENT")
        return self

    def verify(self) -> None:
        if fingerprint(self.model_dump(mode="json", exclude={"content_hash"})) != self.content_hash:
            raise WeeklyError("WEEKLY_REPORT_HASH_INVALID")


def complete_weeks(
    start: date, end: date, now: datetime, market: str
) -> tuple[tuple[date, date], ...]:
    return completed_weeks(start, end, now, market)


class WeeklyReportHistory(DailyDto):
    report_id: UUID
    schedule_id: UUID
    period_start: date
    period_end: date
    recorded_at: AwareDatetime
    usable_until: AwareDatetime
    content_hash: Hash
    usable: bool


class WeeklyReviewPort(Protocol):
    async def preview(self, command: WeeklySave, now: datetime) -> WeeklyPrepared: ...
    async def save(self, command: WeeklySave, preview_hash: str) -> WeeklyConfiguration: ...
    async def mode(self, schedule_id: UUID, command: DailyMode) -> WeeklyConfiguration: ...
    async def configurations(self, offset: int = 0) -> tuple[WeeklyConfiguration, ...]: ...
    async def reports(
        self, schedule_id: UUID | None = None, offset: int = 0
    ) -> tuple[WeeklyReport, ...]: ...
    async def replay(self, report_id: UUID) -> WeeklyReport: ...
    async def runs(self, offset: int = 0) -> tuple[DailyTask, ...]: ...
    async def history(self, offset: int = 0) -> tuple[WeeklyReportHistory, ...]: ...
