"""Independent monthly local consent and immutable portfolio review contracts."""

from calendar import monthrange
from datetime import date, datetime
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


class MonthlyError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class MonthlySave(DailyDto):
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID
    schedule_id: UUID
    expected_version: int = Field(strict=True, ge=0)
    name: Text
    mode: Literal["LOCAL_MONTHLY_REVIEW"]
    frequency: Literal["MONTHLY_AFTER_COMPLETE_CALENDAR_MONTH"]
    market: Literal["SSE", "SZSE"]
    portfolio_id: UUID
    portfolio_instrument_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)
    calendar_import_id: UUID
    coverage_start: date
    coverage_end: date
    quote_source_name: Text
    evidence_source_names: tuple[Text, ...] = Field(max_length=10)
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    retention_days: int = Field(strict=True, ge=1, le=3650)
    pause_method: Literal["MONTHLY_UI_PAUSE_OR_REVOKE"]
    missed_run_policy: Literal["LOCAL_CURRENT_KNOWLEDGE_EXPLICIT_PERIOD"]
    complete_calendar_acknowledgement: Confirmed
    monthly_frequency_acknowledgement: Confirmed
    scope_acknowledgement: Confirmed
    local_only_acknowledgement: Confirmed
    model_profile_ids: tuple[UUID, ...]
    data_profile_ids: tuple[UUID, ...]
    limits: DailyLimits

    @model_validator(mode="after")
    def bounded_local_consent(self) -> Self:
        if (
            self.coverage_start.day != 1
            or self.coverage_end.day
            != monthrange(self.coverage_end.year, self.coverage_end.month)[1]
            or self.coverage_end < self.coverage_start
            or (self.coverage_end - self.coverage_start).days > 365
        ):
            raise ValueError("MONTHLY_COMPLETE_PERIOD_REQUIRED_MAX_366_DATES")
        if self.valid_until <= self.valid_from:
            raise ValueError("MONTHLY_AUTHORIZATION_TIME_INVALID")
        if len(set(self.portfolio_instrument_ids)) != len(self.portfolio_instrument_ids):
            raise ValueError("MONTHLY_DUPLICATE_MEMBER")
        if len(set(self.evidence_source_names)) != len(self.evidence_source_names):
            raise ValueError("MONTHLY_DUPLICATE_SOURCE")
        # A Daily consent or a paid profile can never expand this distinct authorization.
        if (
            self.model_profile_ids
            or self.data_profile_ids
            or self.limits.currency != "NONE"
            or self.limits.task_tokens
            or self.limits.day_tokens
            or self.limits.task_cost != "0"
            or self.limits.day_cost != "0"
        ):
            raise ValueError("MONTHLY_EXTERNAL_CALLS_AND_NONZERO_BUDGET_FORBIDDEN")
        return self

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
            watchlist_instrument_ids=(),
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


class MonthlyPrepared(DailyDto):
    command: MonthlySave
    calendar_hash: Hash
    calendar_source: Text
    calendar_version: Text
    members: tuple[DailyMember, ...]
    prepared_at: AwareDatetime
    content_hash: Hash

    @model_validator(mode="after")
    def exact_scope(self) -> Self:
        if (
            len(self.members) != len(self.command.portfolio_instrument_ids)
            or {row.instrument_id for row in self.members}
            != set(self.command.portfolio_instrument_ids)
            or any(
                not row.in_portfolio or row.in_watchlist or row.market != self.command.market
                for row in self.members
            )
        ):
            raise ValueError("MONTHLY_PREPARED_SCOPE_MISMATCH")
        return self


class MonthlyConfirm(DailyDto):
    command: MonthlySave
    preview_hash: Hash


class MonthlyConfiguration(DailyDto):
    schedule_id: UUID
    revision_id: UUID
    version: int
    enabled: bool
    revoked: bool
    prepared: MonthlyPrepared
    blocker: str | None
    auto_trade: Literal[False] = False


class MonthlyReadReference(DailyDto):
    kind: Literal["THESIS", "ANALYSIS", "RISK", "DECISION"]
    record_id: UUID
    instrument_id: UUID
    recorded_at: AwareDatetime
    status: str
    evidence_ids: tuple[UUID, ...]
    content_hash: Hash
    unknowns: tuple[str, ...] = ()


class MonthlyHoldingReview(DailyDto):
    instrument_id: UUID
    symbol: str
    core_quantity: str
    tactical_quantity: str
    core_change: str | None
    tactical_change: str | None
    quote_status: str
    references: tuple[MonthlyReadReference, ...]
    reentry_assessment: Literal["NOT_PROVIDED"] = "NOT_PROVIDED"
    unknowns: tuple[str, ...]


class MonthlyReport(DailyDto):
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
    phase: Literal["LOCAL_REVIEW", "DEGRADED", "CLOSED_MONTH_SKIPPED"]
    authorization: MonthlyPrepared
    local_inputs: DailyLocalInputs | None
    evidence_diff: DailyEvidenceDiff | None
    baseline_report_id: UUID | None
    baseline_status: Literal["FIRST_RUN_NO_BASELINE", "COMPARABLE_BASELINE"]
    holdings: tuple[MonthlyHoldingReview, ...]
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
            raise ValueError("MONTHLY_REPORT_AUTHORIZATION_OR_PERIOD_MISMATCH")
        if self.local_inputs is not None:
            inputs = self.local_inputs
            if (
                inputs.portfolio.portfolio_id != command.portfolio_id
                or inputs.members != self.authorization.members
                or {p.instrument_id for p in inputs.portfolio.positions}
                != set(command.portfolio_instrument_ids)
                or {p.instrument_id for p in self.holdings} != set(command.portfolio_instrument_ids)
                or any(
                    e.instrument_id not in command.portfolio_instrument_ids
                    or e.source_name
                    not in {*command.evidence_source_names, command.quote_source_name}
                    for e in inputs.evidence
                )
            ):
                raise ValueError("MONTHLY_REPORT_SCOPE_OR_SOURCE_MISMATCH")
        elif (
            self.holdings
            or self.valuation is not None
            or self.quotes
            or self.evidence_diff is not None
        ):
            raise ValueError("MONTHLY_CLOSED_MONTH_HAS_UNAUTHORIZED_CONTENT")
        return self

    def verify(self) -> None:
        if fingerprint(self.model_dump(mode="json", exclude={"content_hash"})) != self.content_hash:
            raise MonthlyError("MONTHLY_REPORT_HASH_INVALID")


def complete_months(
    start: date, end: date, now: datetime, market: str
) -> tuple[tuple[date, date], ...]:
    if now.utcoffset() is None:
        raise MonthlyError("MONTHLY_TIMEZONE_REQUIRED")
    local = now.astimezone(MarketVenue(market).timezone)
    periods = []
    current = start
    while current <= end:
        last = date(current.year, current.month, monthrange(current.year, current.month)[1])
        following = date(current.year + current.month // 12, current.month % 12 + 1, 1)
        if local.date() >= following:
            periods.append((current, last))
        current = following
    return tuple(periods)


class MonthlyReportHistory(DailyDto):
    report_id: UUID
    schedule_id: UUID
    period_start: date
    period_end: date
    recorded_at: AwareDatetime
    usable_until: AwareDatetime
    content_hash: Hash
    usable: bool


class MonthlyReviewPort(Protocol):
    async def preview(self, command: MonthlySave, now: datetime) -> MonthlyPrepared: ...
    async def save(self, command: MonthlySave, preview_hash: str) -> MonthlyConfiguration: ...
    async def mode(self, schedule_id: UUID, command: DailyMode) -> MonthlyConfiguration: ...
    async def configurations(self) -> tuple[MonthlyConfiguration, ...]: ...
    async def reports(self, schedule_id: UUID | None = None) -> tuple[MonthlyReport, ...]: ...
    async def replay(self, report_id: UUID) -> MonthlyReport: ...
    async def runs(self) -> tuple[DailyTask, ...]: ...
    async def history(self) -> tuple[MonthlyReportHistory, ...]: ...
