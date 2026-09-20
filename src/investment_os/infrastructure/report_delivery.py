"""Transactional persistence boundary for synthetic Daily operating reports."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from re import fullmatch
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.reports import DailyOperatingReport
from investment_os.infrastructure.persistence.models import EventLogRecord, OutboxEventRecord
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork

DAILY_REPORT_CREATED = "daily_report.created"
DAILY_REPORT_TOPIC = "reports.daily.created"


@dataclass(frozen=True, slots=True)
class DailyReportRead:
    id: UUID
    as_of: datetime
    content_hash: str
    rendered_markdown: str
    simulation_only: bool


class SqlAlchemyDailyReportReader:
    """Read the newest immutable Daily report event without exposing any mutation path."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def latest(self) -> DailyReportRead | None:
        async with self._session_factory() as session:
            event = (
                await session.scalars(
                    select(EventLogRecord)
                    .where(EventLogRecord.event_type == DAILY_REPORT_CREATED)
                    .order_by(EventLogRecord.occurred_at.desc(), EventLogRecord.id.desc())
                    .limit(1)
                )
            ).one_or_none()
        if event is None:
            return None
        payload = event.payload_json
        as_of = payload.get("as_of")
        content_hash = payload.get("content_hash")
        rendered_markdown = payload.get("rendered_markdown")
        if (
            not isinstance(as_of, str)
            or not isinstance(content_hash, str)
            or not isinstance(rendered_markdown, str)
            or payload.get("simulation_only") is not True
            or fullmatch(r"[0-9a-f]{64}", content_hash) is None
        ):
            raise ValueError("latest daily report event is malformed")
        try:
            parsed_as_of = datetime.fromisoformat(as_of)
        except ValueError as exc:
            raise ValueError("latest daily report has invalid as_of") from exc
        if parsed_as_of.tzinfo is None:
            raise ValueError("latest daily report has naive as_of")
        return DailyReportRead(
            id=event.aggregate_id,
            as_of=parsed_as_of,
            content_hash=content_hash,
            rendered_markdown=rendered_markdown,
            simulation_only=True,
        )


@dataclass(frozen=True, slots=True)
class DailyReportEventHandler:
    """Write one immutable synthetic report event and its outbox record in one UoW."""

    report: DailyOperatingReport
    correlation_id: UUID

    async def __call__(self, uow: SqlAlchemyUnitOfWork) -> None:
        rendered_markdown = self.report.render_markdown()
        content_hash = self.report.content_hash()
        event = EventLogRecord(
            event_type=DAILY_REPORT_CREATED,
            aggregate_type="daily_report",
            aggregate_id=self.report.id,
            payload_json={
                "as_of": self.report.as_of.isoformat(),
                "content_hash": content_hash,
                "rendered_markdown": rendered_markdown,
                "simulation_only": True,
            },
            occurred_at=self.report.as_of,
            correlation_id=self.correlation_id,
            causation_id=None,
            schema_version="1.0",
            metadata_json={"report_kind": "DAILY"},
            created_by="daily_report_job",
        )
        await uow.events.append(event)
        await uow.outbox.add(
            OutboxEventRecord(
                event_id=event.id,
                topic=DAILY_REPORT_TOPIC,
                payload_json={
                    "event_id": str(event.id),
                    "report_id": str(self.report.id),
                    "content_hash": content_hash,
                },
                attempts=0,
                created_by="daily_report_job",
                correlation_id=self.correlation_id,
                causation_id=event.id,
                metadata_json={"report_kind": "DAILY"},
            )
        )


def daily_report_handler(
    report: DailyOperatingReport, correlation_id: UUID
) -> Callable[[SqlAlchemyUnitOfWork], Awaitable[None]]:
    """Bind the report inputs before passing the handler to the durable job executor."""

    return DailyReportEventHandler(report=report, correlation_id=correlation_id)
