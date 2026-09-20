"""Bind an explicit Daily schedule plan to the immutable report delivery handler."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from investment_os.application.reports import DailyOperatingReport
from investment_os.application.schedule import JobCadence, ScheduledJob
from investment_os.infrastructure.report_delivery import daily_report_handler
from investment_os.infrastructure.scheduler import ScheduledJobDispatch, ScheduledJobDispatcher


@dataclass(frozen=True, slots=True)
class DailyReportScheduler:
    """Schedule a Daily report only for its matching explicit business `as_of` instant."""

    dispatcher: ScheduledJobDispatcher

    async def dispatch(
        self,
        *,
        job: ScheduledJob,
        report: DailyOperatingReport,
        dry_run: bool,
        correlation_id: UUID | None = None,
    ) -> ScheduledJobDispatch:
        if job.cadence is not JobCadence.DAILY:
            raise ValueError("daily report requires a DAILY scheduled job")
        if report.as_of != job.as_of:
            raise ValueError("daily report as_of must exactly match the scheduled job as_of")
        report_correlation_id = correlation_id or uuid4()
        return await self.dispatcher.dispatch(
            job=job,
            input_hash=report.content_hash(),
            handler=daily_report_handler(report, report_correlation_id),
            dry_run=dry_run,
            correlation_id=report_correlation_id,
        )
