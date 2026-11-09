"""Versioned zero-egress weekly screening; calendar completeness is explicitly declared."""

from datetime import date, datetime, time, timedelta
from typing import Literal, Protocol, Self
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from investment_os.application.calendar_product import Confirmed
from investment_os.application.complete_weekly_template import CompleteWeeklyTemplate
from investment_os.application.market_data import MarketDto, Text
from investment_os.application.opportunity_schedule import WeeklyMode


class CompleteWeeklyDto(MarketDto):
    schema_version: Literal["2.0"] = "2.0"


class CompleteWeeklySave(CompleteWeeklyDto):
    request_id: UUID
    schedule_id: UUID
    expected_version: int = Field(ge=0)
    name: Text
    venue: Literal["SSE", "SZSE"]
    funnel_run_id: UUID
    calendar_import_id: UUID
    coverage_start: date
    coverage_end: date
    complete_calendar_acknowledgement: Confirmed
    local_only_acknowledgement: Confirmed

    @model_validator(mode="after")
    def complete_weeks(self) -> Self:
        if (
            self.coverage_start.weekday() != 0
            or self.coverage_end.weekday() != 6
            or not 7 <= (self.coverage_end - self.coverage_start).days + 1 <= 364
        ):
            raise ValueError("explicit full Monday-Sunday coverage of one to 52 weeks is required")
        return self


class CompleteWeeklyConfiguration(CompleteWeeklyDto):
    schedule_id: UUID
    revision_id: UUID
    version: int
    name: str
    venue: str
    enabled: bool
    calendar_import_id: UUID
    calendar_source: str
    calendar_version: str
    calendar_hash: str
    template_run_id: UUID
    coverage_start: date
    coverage_end: date
    template: CompleteWeeklyTemplate
    blocker: str | None = None
    scope: Literal["LOCAL_WEEKLY_DETERMINISTIC_ONLY"] = "LOCAL_WEEKLY_DETERMINISTIC_ONLY"
    external_calls: Literal[0] = 0
    model_calls: Literal[0] = 0
    paid_calls: Literal[0] = 0
    auto_trade: Literal[False] = False


class CompleteWeeklyResult(CompleteWeeklyDto):
    task_run_id: UUID
    schedule_id: UUID
    revision_id: UUID
    week_start: date
    scheduled_for: datetime
    as_of: datetime | None
    status: str
    reason_code: str | None
    attempt: int
    funnel_run_id: UUID | None = None
    candidate_count: int | None = None


class CompleteWeeklyOverview(CompleteWeeklyDto):
    configurations: tuple[CompleteWeeklyConfiguration, ...]
    recent_runs: tuple[CompleteWeeklyResult, ...]
    auto_trade: Literal[False] = False


class CompleteWeeklyPort(Protocol):
    async def save(self, command: CompleteWeeklySave) -> CompleteWeeklyConfiguration: ...
    async def mode(self, schedule_id: UUID, command: WeeklyMode) -> CompleteWeeklyConfiguration: ...
    async def overview(self) -> CompleteWeeklyOverview: ...


class CompleteWeeklyService:
    def __init__(self, port: CompleteWeeklyPort):
        self._port = port

    async def save(self, command: CompleteWeeklySave) -> CompleteWeeklyConfiguration:
        return await self._port.save(command)

    async def mode(self, schedule_id: UUID, command: WeeklyMode) -> CompleteWeeklyConfiguration:
        return await self._port.mode(schedule_id, command)

    async def overview(self) -> CompleteWeeklyOverview:
        return await self._port.overview()


def covered_weeks(start: date, end: date) -> tuple[date, ...]:
    return tuple(
        start + timedelta(days=7 * offset) for offset in range(((end - start).days + 1) // 7)
    )


def week_due(week_start: date) -> datetime:
    # Execute only after the declared full natural week ends, not by guessing Friday trading.
    return datetime.combine(week_start + timedelta(days=7), time(), ZoneInfo("Asia/Shanghai"))
