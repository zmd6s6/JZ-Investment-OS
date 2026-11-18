"""Read original Calendar task sources and report events; never dispatch or backfill."""

import base64
import binascii
from datetime import date
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.calendar_product import CalendarProductError, CalendarStatusReport
from investment_os.application.calendar_task_history import (
    CalendarTaskCursor,
    CalendarTaskDetail,
    CalendarTaskPage,
    CalendarTaskSource,
    CalendarTaskSummary,
)
from investment_os.application.schedule import MarketVenue
from investment_os.infrastructure.calendar_product import REPORT_EVENT, _hash, _preview
from investment_os.infrastructure.persistence.calendar_models import (
    CalendarImportRecord,
    MarketSessionRecord,
)
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    EventLogRecord,
    TaskRunRecord,
)


def summary(task: TaskRunRecord) -> CalendarTaskSummary:
    error = task.error_json or {}
    reason = error.get("code", error.get("type"))
    return CalendarTaskSummary(
        task_run_id=task.id,
        task_name=task.task_name,
        task_status=task.status,
        attempt=task.attempt,
        created_at=task.created_at,
        scheduled_for=task.scheduled_for,
        started_at=task.started_at,
        finished_at=task.finished_at,
        reason_code=reason if isinstance(reason, str) else None,
        input_hash=task.input_hash,
    )


class SqlCalendarTaskHistory:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def tasks(self, cursor: str | None = None) -> CalendarTaskPage:
        statement = select(TaskRunRecord).where(
            TaskRunRecord.task_name.startswith("calendar_status_", autoescape=True)
        )
        if cursor is not None:
            try:
                if len(cursor) > 1024:
                    raise ValueError("cursor too long")
                boundary = CalendarTaskCursor.model_validate_json(
                    base64.b64decode(cursor, altchars=b"-_", validate=True)
                )
            except (ValueError, binascii.Error):
                raise CalendarProductError(
                    "CALENDAR_TASK_CURSOR_INVALID", "日历任务分页标识无效, 请刷新历史后重试。"
                ) from None
            statement = statement.where(
                tuple_(TaskRunRecord.created_at, TaskRunRecord.id)
                < tuple_(literal(boundary.created_at), literal(boundary.task_run_id))
            )
        async with self.sessions() as session:
            rows = tuple(
                await session.scalars(
                    statement.order_by(
                        TaskRunRecord.created_at.desc(), TaskRunRecord.id.desc()
                    ).limit(51)
                )
            )
            next_cursor = None
            if len(rows) > 50:
                last = rows[49]
                next_cursor = base64.urlsafe_b64encode(
                    CalendarTaskCursor(created_at=last.created_at, task_run_id=last.id)
                    .model_dump_json()
                    .encode()
                ).decode()
            return CalendarTaskPage(
                items=tuple(summary(row) for row in rows[:50]), next_cursor=next_cursor
            )

    async def source(self, session: AsyncSession, task: TaskRunRecord) -> CalendarTaskSource | None:
        try:
            kind, venue_text, day_text, import_text = task.idempotency_key.split(":")
            venue, day, import_id = (
                MarketVenue(venue_text),
                date.fromisoformat(day_text),
                UUID(import_text),
            )
            if (
                kind != "calendar-status"
                or task.task_name != f"calendar_status_{venue.value}"
                or day.isoformat() != day_text
                or str(import_id) != import_text
            ):
                return None
        except (ValueError, TypeError):
            return None
        record = await session.get(CalendarImportRecord, import_id)
        if record is None or record.venue != venue.value:
            return None
        try:
            await _preview(session, record)
        except (CalendarProductError, ValueError):
            return None
        original = await session.scalar(
            select(MarketSessionRecord).where(
                MarketSessionRecord.import_id == import_id, MarketSessionRecord.business_date == day
            )
        )
        if (
            original is None
            or original.close_at_utc != task.scheduled_for
            or _hash(
                {
                    "venue": venue.value,
                    "business_date": day,
                    "close_at": original.close_at_utc,
                    "calendar_hash": record.content_hash,
                }
            )
            != task.input_hash
        ):
            return None
        return CalendarTaskSource(
            venue=venue,
            market_timezone=venue.timezone.key,
            business_date=day,
            close_at_utc=original.close_at_utc,
            calendar_import_id=record.id,
            calendar_session_id=original.id,
            imported_at=record.imported_at,
            source_name=record.source_name,
            source_version=record.source_version,
            calendar_hash=record.content_hash,
        )

    async def task(self, task_run_id: UUID) -> CalendarTaskDetail:
        async with self.sessions() as session:
            task = await session.scalar(
                select(TaskRunRecord).where(
                    TaskRunRecord.id == task_run_id,
                    TaskRunRecord.task_name.startswith("calendar_status_", autoescape=True),
                )
            )
            if task is None:
                raise CalendarProductError(
                    "CALENDAR_TASK_NOT_FOUND", "原日历状态任务不存在或属于其他任务类型。"
                )
            source = await self.source(session, task)
            unknowns = ["ATTEMPT_TIMELINE_NOT_RECORDED"]
            if source is None:
                unknowns.append("ORIGINAL_SOURCE_MISSING_OR_UNVERIFIED")
            reports = tuple(
                await session.scalars(
                    select(EventLogRecord).where(
                        EventLogRecord.event_type == REPORT_EVENT,
                        EventLogRecord.aggregate_id == task.id,
                    )
                )
            )
            verified = None
            persisted_hash = None
            if len(reports) == 1 and source and task.status == "SUCCEEDED":
                event = reports[0]
                try:
                    report = CalendarStatusReport.model_validate(event.payload_json)
                    if (
                        event.aggregate_type == "calendar_product"
                        and event.schema_version == "1.0"
                        and report.venue == source.venue
                        and report.business_date == source.business_date
                        and report.as_of == task.scheduled_for
                        and report.calendar_import_id == source.calendar_import_id
                        and report.calendar_hash == source.calendar_hash
                        and report.source_name == source.source_name
                        and report.source_version == source.source_version
                    ):
                        # The persisted Audit hash covers the ORIGINAL JSON, never DTO defaults.
                        audits = tuple(
                            await session.scalars(
                                select(AuditLogRecord).where(
                                    AuditLogRecord.entity_id == task.id,
                                    AuditLogRecord.operation == REPORT_EVENT,
                                    AuditLogRecord.entity_type == "calendar_product",
                                    AuditLogRecord.correlation_id == event.correlation_id,
                                    AuditLogRecord.after_hash == _hash(event.payload_json),
                                )
                            )
                        )
                        if len(audits) == 1:
                            verified, persisted_hash = event, audits[0].after_hash
                except ValidationError:
                    pass
            if verified is None:
                unknowns.append(
                    "REPORT_MISSING_OR_UNVERIFIED"
                    if reports or task.status == "SUCCEEDED"
                    else "NO_COMMITTED_STATUS_REPORT"
                )
            if task.status not in {"RUNNING", "SUCCEEDED", "FAILED"}:
                unknowns.append("UNSUPPORTED_RECORDED_STATUS")
            return CalendarTaskDetail(
                **summary(task).model_dump(),
                idempotency_key=task.idempotency_key,
                source=source,
                report_event_id=verified.id if verified else None,
                report_recorded_at=verified.occurred_at if verified else None,
                report_json=verified.payload_json if verified else None,
                report_hash=persisted_hash,
                unknowns=tuple(unknowns),
            )
