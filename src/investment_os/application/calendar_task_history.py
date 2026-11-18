"""Read-only original Calendar STATUS_ONLY TaskRun audit contracts."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, JsonValue

from investment_os.application.calendar_product import CalendarDto
from investment_os.application.schedule import MarketVenue


class CalendarTaskCursor(CalendarDto):
    namespace: Literal["calendar_status"]
    created_at: AwareDatetime
    task_run_id: UUID


class CalendarTaskSummary(CalendarDto):
    schema_version: Literal["1.0"] = "1.0"
    task_run_id: UUID
    task_name: str
    task_status: str
    attempt: int
    created_at: AwareDatetime
    scheduled_for: AwareDatetime
    started_at: AwareDatetime | None
    finished_at: AwareDatetime | None
    reason_code: str | None
    input_hash: str
    auto_trade: Literal[False] = False


class CalendarTaskPage(CalendarDto):
    schema_version: Literal["1.0"] = "1.0"
    items: tuple[CalendarTaskSummary, ...]
    next_cursor: str | None
    page_size: Literal[50] = 50
    ordering: Literal["created_at_desc_task_id_desc"] = "created_at_desc_task_id_desc"
    auto_trade: Literal[False] = False


class CalendarTaskSource(CalendarDto):
    venue: MarketVenue
    market_timezone: str
    business_date: date
    close_at_utc: AwareDatetime
    calendar_import_id: UUID
    calendar_session_id: UUID
    imported_at: AwareDatetime
    source_name: str
    source_version: str
    calendar_hash: str
    source_verification: Literal["SOURCE_DECLARED_UNVERIFIED"] = "SOURCE_DECLARED_UNVERIFIED"


class CalendarTaskDetail(CalendarTaskSummary):
    idempotency_key: str
    source: CalendarTaskSource | None = None
    report_event_id: UUID | None = None
    report_recorded_at: AwareDatetime | None = None
    report_json: dict[str, JsonValue] | None = None
    report_hash: str | None = None
    unknowns: tuple[str, ...]
    attempt_history: Literal["NOT_PROVIDED_CURRENT_RECORDED_ATTEMPT_ONLY"] = (
        "NOT_PROVIDED_CURRENT_RECORDED_ATTEMPT_ONLY"
    )
