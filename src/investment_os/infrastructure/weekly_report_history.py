"""Read-only exact and bounded history for immutable weekly local reports.

The caller authenticates schedule ownership before invoking these functions.
No task enqueue, provider access, approval, or report mutation occurs here.
"""
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class WeeklyHistoryError(ValueError):
    pass


@dataclass(frozen=True)
class WeeklyReportSummary:
    id: UUID
    schedule_id: UUID
    week_start: date
    week_end: date
    recorded_at: datetime
    content_hash: str


async def list_weekly_reports(
    session: AsyncSession, *, schedule_id: UUID, limit: int = 25, offset: int = 0
) -> tuple[WeeklyReportSummary, ...]:
    """Stable bounded history; an empty result is not a total count."""
    if not 1 <= limit <= 100 or not 0 <= offset <= 10000:
        raise WeeklyHistoryError("WEEKLY_HISTORY_INVALID_PAGE")
    rows = (await session.execute(
        text("""
            SELECT id, schedule_id, week_start, week_end, recorded_at, content_hash
            FROM weekly_local_report
            WHERE schedule_id = :schedule_id
            ORDER BY week_start DESC, id DESC
            LIMIT :limit OFFSET :offset
        """),
        {"schedule_id": schedule_id, "limit": limit, "offset": offset},
    )).mappings().all()
    return tuple(WeeklyReportSummary(**dict(row)) for row in rows)


async def get_weekly_report(
    session: AsyncSession, *, schedule_id: UUID, report_id: UUID
) -> dict:
    """Exact scoped lookup, never substitute the newest report."""
    row = (await session.execute(
        text("""
            SELECT id, schedule_id, revision_id, task_run_id, week_start,
                   week_end, knowledge_as_of, recorded_at, report_json, content_hash
            FROM weekly_local_report
            WHERE id = :report_id AND schedule_id = :schedule_id
        """),
        {"schedule_id": schedule_id, "report_id": report_id},
    )).mappings().one_or_none()
    if row is None:
        raise WeeklyHistoryError("WEEKLY_REPORT_NOT_FOUND")
    return dict(row)
