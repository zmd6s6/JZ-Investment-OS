"""Explicit, auditable calendar imports for unpaid operational status reports only."""

import csv
import io
import json
from datetime import UTC, date, datetime, time
from hashlib import sha256
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
)

from investment_os.application.schedule import MarketVenue

MAX_CALENDAR_SESSIONS = 1000
CalendarText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


def _confirmed(value: object) -> Literal[True]:
    if value is not True:
        raise ValueError("explicit boolean confirmation is required")
    return True


Confirmed = Annotated[Literal[True], BeforeValidator(_confirmed)]


class CalendarDto(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CalendarInput(CalendarDto):
    venue: MarketVenue
    source_name: CalendarText
    source_version: CalendarText
    csv_text: str = Field(min_length=1, max_length=100_000)
    confirmed_source: Confirmed


class CalendarImportCommand(CalendarInput):
    request_id: UUID
    expected_version: int = Field(ge=0)


class CalendarModeCommand(CalendarDto):
    request_id: UUID
    expected_version: int = Field(ge=1)
    enabled: StrictBool
    status_only_acknowledgement: Confirmed


class CalendarSessionInput(CalendarDto):
    business_date: date
    close_at_utc: AwareDatetime


class CalendarPreview(CalendarDto):
    schema_version: Literal["1.0"] = "1.0"
    venue: MarketVenue
    market_timezone: str
    source_name: str
    source_version: str
    content_hash: str
    sessions: tuple[CalendarSessionInput, ...]


class CalendarConfigurationView(CalendarDto):
    venue: MarketVenue
    market_timezone: str
    version: int
    import_id: UUID
    enabled: bool
    source_name: str
    source_version: str
    content_hash: str
    imported_at: datetime
    session_count: int
    first_business_date: date
    last_business_date: date
    next_close_at: datetime | None


class CalendarStatusReport(CalendarDto):
    report_kind: Literal["CALENDAR_STATUS_ONLY"]
    venue: MarketVenue
    business_date: date
    as_of: AwareDatetime
    calendar_import_id: UUID
    calendar_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_name: str
    source_version: str
    message: str
    auto_trade: Literal[False]
    paid_calls: Literal[0]


class CalendarRunView(CalendarDto):
    task_run_id: UUID
    task_name: str
    as_of: datetime
    status: str
    attempt: int
    started_at: datetime
    finished_at: datetime | None
    error_code: str | None
    report: CalendarStatusReport | None


class CalendarOverview(CalendarDto):
    schema_version: Literal["1.0"] = "1.0"
    scope: Literal["CALENDAR_STATUS_ONLY_NO_PAID_CALLS"] = "CALENDAR_STATUS_ONLY_NO_PAID_CALLS"
    auto_trade: Literal[False] = False
    configurations: tuple[CalendarConfigurationView, ...]
    recent_runs: tuple[CalendarRunView, ...]


class CalendarProductError(Exception):
    def __init__(self, code: str, message: str, *, conflict: bool = False):
        super().__init__(message)
        self.code, self.message, self.conflict = code, message, conflict


def calendar_hash(
    venue: MarketVenue,
    source_name: str,
    source_version: str,
    sessions: tuple[CalendarSessionInput, ...],
) -> str:
    payload = {
        "venue": venue.value,
        "source_name": source_name,
        "source_version": source_version,
        "sessions": [s.model_dump(mode="json") for s in sessions],
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def preview_calendar(command: CalendarInput) -> CalendarPreview:
    """Reject partial CSVs, duplicate dates and ambiguous/nonexistent local close instants."""
    try:
        reader = csv.DictReader(io.StringIO(command.csv_text.lstrip("\ufeff")), strict=True)
        if reader.fieldnames != ["business_date", "close_at"]:
            raise ValueError("header")
        dates: set[date] = set()
        sessions: list[CalendarSessionInput] = []
        for row in reader:
            if (
                len(sessions) >= MAX_CALENDAR_SESSIONS
                or None in row
                or set(row) != {"business_date", "close_at"}
            ):
                raise ValueError("row limit or shape")
            day_text, close_text = row["business_date"], row["close_at"]
            if (
                day_text is None
                or close_text is None
                or len(day_text) != 10
                or len(close_text) != 5
                or close_text[2] != ":"
            ):
                raise ValueError("row format")
            day, close = date.fromisoformat(day_text), time.fromisoformat(close_text)
            if day.isoformat() != day_text or day in dates or close.tzinfo is not None:
                raise ValueError("duplicate date or timezone")
            local = datetime.combine(day, close, tzinfo=command.venue.timezone)
            utc = local.astimezone(UTC)
            if (
                utc.astimezone(command.venue.timezone).replace(tzinfo=None)
                != local.replace(tzinfo=None)
                or local.replace(fold=0).utcoffset() != local.replace(fold=1).utcoffset()
            ):
                raise ValueError("ambiguous or nonexistent local close")
            dates.add(day)
            sessions.append(CalendarSessionInput(business_date=day, close_at_utc=utc))
        if not sessions:
            raise ValueError("empty calendar")
    except (ValueError, csv.Error) as exc:
        raise CalendarProductError(
            "CALENDAR_INPUT_INVALID",
            "日历格式无效。请使用business_date,close_at表头、YYYY-MM-DD日期和HH:MM本地收盘时间; "
            "日期不可重复, 最多1000条, 不接受夏令时歧义时刻。整批未导入。",
        ) from exc
    ordered = tuple(sorted(sessions, key=lambda s: s.business_date))
    return CalendarPreview(
        venue=command.venue,
        market_timezone=command.venue.timezone.key,
        source_name=command.source_name,
        source_version=command.source_version,
        content_hash=calendar_hash(
            command.venue, command.source_name, command.source_version, ordered
        ),
        sessions=ordered,
    )


class CalendarProductPort(Protocol):
    async def overview(self) -> CalendarOverview: ...
    async def import_calendar(
        self, command: CalendarImportCommand, preview: CalendarPreview
    ) -> CalendarConfigurationView: ...
    async def set_mode(
        self, venue: MarketVenue, command: CalendarModeCommand
    ) -> CalendarConfigurationView: ...


class CalendarProductService:
    def __init__(self, port: CalendarProductPort):
        self._port = port

    async def overview(self) -> CalendarOverview:
        return await self._port.overview()

    async def import_calendar(self, command: CalendarImportCommand) -> CalendarConfigurationView:
        return await self._port.import_calendar(command, preview_calendar(command))

    async def set_mode(
        self, venue: MarketVenue, command: CalendarModeCommand
    ) -> CalendarConfigurationView:
        return await self._port.set_mode(venue, command)
