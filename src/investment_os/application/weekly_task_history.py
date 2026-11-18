"""Read-only audit contracts for both already-persisted weekly opportunity protocols."""

from datetime import date
from typing import Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime

from investment_os.application.market_data import MarketDto

WeeklyProtocol = Literal["1.0", "2.0"]


class WeeklyTaskCursor(MarketDto):
    protocol: WeeklyProtocol
    created_at: AwareDatetime
    task_run_id: UUID


class WeeklyTaskSummary(MarketDto):
    schema_version: Literal["1.0"] = "1.0"
    protocol: WeeklyProtocol
    task_run_id: UUID
    schedule_id: UUID | None
    revision_id: UUID | None
    week_start: date | None
    scheduled_for: AwareDatetime
    created_at: AwareDatetime
    started_at: AwareDatetime
    finished_at: AwareDatetime | None
    task_status: str
    attempt: int
    reason_code: str | None
    input_hash: str
    result_status: str | None = None
    as_of: AwareDatetime | None = None
    candidate_count: int | None = None
    unknowns: tuple[str, ...] = ()
    auto_trade: Literal[False] = False


class WeeklyTaskPage(MarketDto):
    schema_version: Literal["1.0"] = "1.0"
    protocol: WeeklyProtocol
    items: tuple[WeeklyTaskSummary, ...]
    next_cursor: str | None
    page_size: Literal[50] = 50
    ordering: Literal["created_at_desc_task_id_desc"] = "created_at_desc_task_id_desc"
    auto_trade: Literal[False] = False


class WeeklyTaskProvenance(MarketDto):
    name: str
    venue: str
    revision_hash: str
    calendar_import_id: UUID
    calendar_hash: str
    calendar_source: str | None
    calendar_version: str | None
    template_run_id: UUID
    source_name: str
    source_locator: str
    quote_source_name: str
    fact_source_name: str
    snapshot_id: UUID | None = None
    snapshot_hash: str | None = None
    coverage_start: date
    coverage_end: date
    source_verification: Literal["SOURCE_DECLARED_UNVERIFIED"] = "SOURCE_DECLARED_UNVERIFIED"


class WeeklyTaskDetail(WeeklyTaskSummary):
    provenance: WeeklyTaskProvenance | None = None
    funnel_run_id: UUID | None = None
    funnel_hash: str | None = None
    attempt_history: Literal["NOT_PROVIDED_CURRENT_RECORDED_ATTEMPT_ONLY"] = (
        "NOT_PROVIDED_CURRENT_RECORDED_ATTEMPT_ONLY"
    )


class WeeklyTaskHistoryPort(Protocol):
    async def tasks(self, cursor: str | None = None) -> WeeklyTaskPage: ...
    async def task(self, task_run_id: UUID) -> WeeklyTaskDetail: ...
