"""Weekly scope capture reuses read-only membership locks, never Daily consent writes."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from investment_os.application.calendar_product import CalendarSessionInput, calendar_hash
from investment_os.application.daily_runtime import DailyError
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.application.schedule import MarketVenue
from investment_os.application.weekly_review import WeeklyError, WeeklyPrepared, WeeklySave
from investment_os.infrastructure.daily_runtime_setup import capture_scope
from investment_os.infrastructure.persistence.calendar_models import (
    CalendarConfigurationRecord,
    CalendarImportRecord,
    MarketSessionRecord,
)


def prepared_hash(prepared: WeeklyPrepared) -> str:
    return fingerprint(prepared.model_dump(mode="json", exclude={"content_hash", "prepared_at"}))


async def capture(
    session: AsyncSession, command: WeeklySave, now: datetime, *, lock: bool
) -> tuple[WeeklyPrepared, tuple[CalendarSessionInput, ...]]:
    if not command.valid_from <= now < command.valid_until:
        raise WeeklyError("WEEKLY_AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID")
    try:
        members = await capture_scope(session, command.local_read_scope(), lock=lock)
    except DailyError as exc:
        raise WeeklyError(exc.code.replace("DAILY_", "WEEKLY_")) from None
    statement = select(CalendarConfigurationRecord).where(
        CalendarConfigurationRecord.venue == command.market
    )
    if lock:
        statement = statement.with_for_update(read=True)
    pointer = await session.scalar(statement)
    source = await session.get(CalendarImportRecord, command.calendar_import_id)
    if (
        pointer is None
        or source is None
        or pointer.active_import_id != source.id
        or source.venue != command.market
    ):
        raise WeeklyError("WEEKLY_CALENDAR_CHANGED_OR_MISSING")
    rows = (
        await session.scalars(
            select(MarketSessionRecord)
            .where(MarketSessionRecord.import_id == source.id)
            .order_by(MarketSessionRecord.business_date)
        )
    ).all()
    days = tuple(
        CalendarSessionInput(business_date=row.business_date, close_at_utc=row.close_at_utc)
        for row in rows
    )
    venue = MarketVenue(command.market)
    if (
        not days
        or len(days) > 1000
        or any(
            day.close_at_utc.astimezone(venue.timezone).date() != day.business_date for day in days
        )
        or calendar_hash(venue, source.source_name, source.source_version, days)
        != source.content_hash
    ):
        raise WeeklyError("WEEKLY_CALENDAR_HASH_INVALID")
    expected_dates = {
        command.coverage_start + timedelta(days=i)
        for i in range((command.coverage_end - command.coverage_start).days + 1)
    }
    actual_open = {
        day.business_date
        for day in days
        if command.coverage_start <= day.business_date <= command.coverage_end
    }
    if (
        set(command.calendar_days) != expected_dates
        or {day for day, status in command.calendar_days.items() if status == "OPEN"} != actual_open
    ):
        raise WeeklyError("WEEKLY_CALENDAR_DATE_MANIFEST_MISSING_OR_MISMATCH")
    # Every closed day is explicitly recorded; no weekday/holiday inference. The imported
    # source hash and all open sessions are independently reread above, under the same lock.
    prepared = WeeklyPrepared(
        command=command,
        calendar_hash=source.content_hash,
        calendar_source=source.source_name,
        calendar_version=source.source_version,
        members=members,
        prepared_at=now,
        content_hash="0" * 64,
    )
    return prepared.model_copy(update={"content_hash": prepared_hash(prepared)}), days
