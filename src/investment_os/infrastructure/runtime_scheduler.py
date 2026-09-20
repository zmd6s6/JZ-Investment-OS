"""Calendar-configured synthetic job dispatch for the worker runtime."""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.reports import (
    DailyOperatingReport,
    DailyReportSection,
    DailyReportSectionKind,
    ReportStatement,
    ReportStatementKind,
)
from investment_os.application.schedule import (
    ExplicitTradingCalendar,
    JobCadence,
    MarketVenue,
    ScheduledJob,
    TradingSession,
    jobs_for_session,
)
from investment_os.infrastructure.daily_report_scheduler import DailyReportScheduler
from investment_os.infrastructure.persistence.jobs import ReliableJobExecutor
from investment_os.infrastructure.persistence.models import EventLogRecord, OutboxEventRecord
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork
from investment_os.infrastructure.scheduler import ScheduledJobDispatch, ScheduledJobDispatcher

SCHEDULED_JOB_COMPLETED = "scheduled_job.completed"
SCHEDULED_JOB_TOPIC = "scheduler.job.completed"
MAX_CALENDAR_DOCUMENT_CHARACTERS = 512_000


class _CalendarSessionDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_date: date
    close_at: time


class _CalendarDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    venue: MarketVenue
    sessions: tuple[_CalendarSessionDocument, ...] = Field(min_length=1)


def load_synthetic_calendar(path: Path) -> ExplicitTradingCalendar:
    """Load only an explicit, bounded, schema-validated synthetic calendar document."""

    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError("synthetic scheduler calendar is unavailable") from exc
    if len(raw) > MAX_CALENDAR_DOCUMENT_CHARACTERS:
        raise ValueError("synthetic scheduler calendar exceeds the size limit")
    try:
        document = _CalendarDocument.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError("synthetic scheduler calendar is invalid") from exc
    return ExplicitTradingCalendar(
        sessions=tuple(
            TradingSession(business_date=session.business_date, close_at=session.close_at)
            for session in document.sessions
        ),
        venue=document.venue,
    )


def _daily_report(job: ScheduledJob) -> DailyOperatingReport:
    """Create a synthetic no-data report; it cannot express an investment action."""

    return DailyOperatingReport(
        as_of=job.as_of,
        sections=tuple(
            DailyReportSection(
                kind=kind,
                statements=(
                    ReportStatement(
                        kind=ReportStatementKind.OPERATIONAL_EXCEPTION,
                        content=(
                            "Synthetic calendar-only runtime: no research, portfolio, approval, "
                            "or execution action was produced."
                        ),
                    ),
                )
                if kind is DailyReportSectionKind.DATA_AND_OPERATIONAL_EXCEPTIONS
                else (),
            )
            for kind in DailyReportSectionKind
        ),
    )


def _job_input_hash(job: ScheduledJob) -> str:
    payload = "|".join(
        (
            "synthetic-scheduler-v1",
            job.name,
            job.cadence.value,
            job.as_of.astimezone(UTC).isoformat(),
            job.scheduled_for.astimezone(UTC).isoformat(),
        )
    )
    return sha256(payload.encode("utf-8")).hexdigest()


async def _scheduled_job_handler(
    uow: SqlAlchemyUnitOfWork,
    *,
    job: ScheduledJob,
    correlation_id: UUID,
) -> None:
    """Record non-Daily cadence completion without creating any decision or execution path."""

    event = EventLogRecord(
        event_type=SCHEDULED_JOB_COMPLETED,
        aggregate_type="scheduled_job",
        aggregate_id=uuid4(),
        payload_json={
            "name": job.name,
            "cadence": job.cadence.value,
            "as_of": job.as_of.isoformat(),
            "scheduled_for": job.scheduled_for.isoformat(),
            "simulation_only": True,
        },
        occurred_at=job.as_of,
        correlation_id=correlation_id,
        causation_id=None,
        schema_version="1.0",
        metadata_json={"scheduler": "explicit_synthetic_calendar"},
        created_by="worker_scheduler",
    )
    await uow.events.append(event)
    await uow.outbox.add(
        OutboxEventRecord(
            event_id=event.id,
            topic=SCHEDULED_JOB_TOPIC,
            payload_json={
                "event_id": str(event.id),
                "input_hash": _job_input_hash(job),
                "simulation_only": True,
            },
            attempts=0,
            created_by="worker_scheduler",
            correlation_id=correlation_id,
            causation_id=event.id,
            metadata_json={"scheduler": "explicit_synthetic_calendar"},
        )
    )


@dataclass(slots=True)
class RuntimeScheduleRunner:
    """Run at most a bounded set of explicit, already-closed market sessions per poll."""

    session_factory: async_sessionmaker[AsyncSession]
    calendar: ExplicitTradingCalendar
    max_replay_sessions: int

    def __post_init__(self) -> None:
        if self.max_replay_sessions < 1:
            raise ValueError("max_replay_sessions must be at least one")

    async def dispatch_due(self, *, now: datetime) -> tuple[ScheduledJobDispatch, ...]:
        if now.tzinfo is None:
            raise ValueError("scheduler now must be timezone-aware")
        now_utc = now.astimezone(UTC)
        due_sessions = tuple(
            sorted(
                (
                    session
                    for session in self.calendar.sessions
                    if session.scheduled_for(market_timezone=self.calendar.timezone) <= now_utc
                ),
                key=lambda session: session.scheduled_for(market_timezone=self.calendar.timezone),
            )
        )[-self.max_replay_sessions :]
        dispatcher = ScheduledJobDispatcher(ReliableJobExecutor(self.session_factory))
        daily_scheduler = DailyReportScheduler(dispatcher)
        results: list[ScheduledJobDispatch] = []
        for session in due_sessions:
            for job in jobs_for_session(calendar=self.calendar, session=session):
                correlation_id = uuid4()
                if job.cadence is JobCadence.DAILY:
                    results.append(
                        await daily_scheduler.dispatch(
                            job=job,
                            report=_daily_report(job),
                            dry_run=False,
                            correlation_id=correlation_id,
                        )
                    )
                    continue

                async def handler(
                    uow: SqlAlchemyUnitOfWork,
                    scheduled_job: ScheduledJob = job,
                    scheduled_correlation_id: UUID = correlation_id,
                ) -> None:
                    await _scheduled_job_handler(
                        uow,
                        job=scheduled_job,
                        correlation_id=scheduled_correlation_id,
                    )

                results.append(
                    await dispatcher.dispatch(
                        job=job,
                        input_hash=_job_input_hash(job),
                        handler=handler,
                        dry_run=False,
                        correlation_id=correlation_id,
                    )
                )
        return tuple(results)
