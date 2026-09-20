"""Transactional persistence boundary for synthetic Daily operating reports."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from investment_os.application.reports import DailyOperatingReport
from investment_os.infrastructure.persistence.models import EventLogRecord, OutboxEventRecord
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork

DAILY_REPORT_CREATED = "daily_report.created"
DAILY_REPORT_TOPIC = "reports.daily.created"


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
