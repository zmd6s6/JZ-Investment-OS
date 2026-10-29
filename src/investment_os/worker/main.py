"""Worker bootstrap loop with database-backed readiness."""

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncEngine

from investment_os.application.health import AsyncClosable, ReadinessProbe
from investment_os.infrastructure.calendar_product import PersistedCalendarStatusRunner
from investment_os.infrastructure.database import (
    DatabaseReadinessProbe,
    create_database_engine,
    create_session_factory,
)
from investment_os.infrastructure.runtime_scheduler import (
    RuntimeScheduleRunner,
    load_synthetic_calendar,
)
from investment_os.infrastructure.settings import Settings, get_settings
from investment_os.worker.analysis_bootstrap import analysis_worker
from investment_os.worker.weekly_funnel import weekly_worker

LOGGER = logging.getLogger(__name__)


class CalendarScheduler(Protocol):
    async def dispatch_due(self, *, now: datetime) -> object: ...


def _set_ready_marker(ready_file: Path, *, ready: bool) -> None:
    if ready:
        ready_file.parent.mkdir(parents=True, exist_ok=True)
        ready_file.touch()
    else:
        ready_file.unlink(missing_ok=True)


async def refresh_ready_marker(probe: ReadinessProbe, ready_file: Path) -> bool:
    """Reflect one sanitized readiness check in a local container marker file."""

    check = await probe.check()
    await asyncio.to_thread(_set_ready_marker, ready_file, ready=check.ready)
    return check.ready


class WorkerRuntime:
    """Own worker readiness and optional calendar-configured synthetic scheduling."""

    def __init__(
        self,
        *,
        probe: DatabaseReadinessProbe,
        ready_file: Path,
        scheduler: CalendarScheduler | None,
        scheduler_engine: AsyncEngine | None,
        analysis: CalendarScheduler | None = None,
        analysis_resources: AsyncClosable | None = None,
        weekly: CalendarScheduler | None = None,
    ) -> None:
        self._probe = probe
        self._ready_file = ready_file
        self._scheduler = scheduler
        self._scheduler_engine = scheduler_engine
        self._analysis = analysis
        self._analysis_resources = analysis_resources
        self._analysis_task: asyncio.Task[object] | None = None
        self._weekly = weekly

    @classmethod
    def from_settings(cls, settings: Settings) -> "WorkerRuntime":
        scheduler: CalendarScheduler | None = None
        scheduler_engine: AsyncEngine | None = None
        if settings.worker_schedule_calendar_path is not None:
            calendar = load_synthetic_calendar(settings.worker_schedule_calendar_path)
            engine = create_database_engine(settings.database_url)
            scheduler_engine = engine
            scheduler = RuntimeScheduleRunner(
                session_factory=create_session_factory(engine),
                calendar=calendar,
                max_replay_sessions=settings.worker_scheduler_max_replay_sessions,
            )
        else:
            # No imported/explicitly enabled calendar means no due work; never invent sessions.
            engine = create_database_engine(settings.database_url)
            scheduler_engine = engine
            scheduler = PersistedCalendarStatusRunner(
                create_session_factory(engine),
                max_replay_sessions=settings.worker_scheduler_max_replay_sessions,
            )
        analysis, resources = analysis_worker(create_session_factory(engine), settings)
        return cls(
            analysis=analysis,
            analysis_resources=resources,
            weekly=weekly_worker(create_session_factory(engine)),
            probe=DatabaseReadinessProbe(settings.database_url),
            ready_file=settings.worker_ready_file,
            scheduler=scheduler,
            scheduler_engine=scheduler_engine,
        )

    async def run_once(self, *, now: datetime | None = None) -> bool:
        ready = await refresh_ready_marker(self._probe, self._ready_file)
        if ready and self._scheduler is not None:
            scheduled_now = now or datetime.now(UTC)
            await self._scheduler.dispatch_due(now=scheduled_now)
        if ready and self._weekly is not None:
            try:
                await self._weekly.dispatch_due(now=now or datetime.now(UTC))
            except Exception:
                LOGGER.error("weekly_local_dispatch_failed")
        if (
            ready
            and self._analysis is not None
            and (self._analysis_task is None or self._analysis_task.done())
        ):
            if self._analysis_task is not None:
                try:
                    self._analysis_task.result()
                except Exception:
                    LOGGER.error("analysis_dispatch_failed")
            self._analysis_task = asyncio.create_task(
                self._analysis.dispatch_due(now=now or datetime.now(UTC))
            )
        return ready

    async def close(self) -> None:
        if self._analysis_task is not None:
            self._analysis_task.cancel()
            try:
                await self._analysis_task
            except asyncio.CancelledError:
                pass
            except Exception:
                LOGGER.error("analysis_shutdown_failed")
        if self._analysis_resources is not None:
            await self._analysis_resources.close()
        if self._scheduler_engine is not None:
            await self._scheduler_engine.dispose()
        await self._probe.close()


async def run_worker(settings: Settings) -> None:
    """Maintain readiness and poll an explicitly configured synthetic market calendar."""

    runtime = WorkerRuntime.from_settings(settings)
    LOGGER.info("worker_bootstrap_started")
    try:
        while True:
            ready = await runtime.run_once()
            if not ready:
                LOGGER.warning("worker_database_not_ready")
            await asyncio.sleep(settings.worker_poll_seconds)
    finally:
        await asyncio.to_thread(settings.worker_ready_file.unlink, missing_ok=True)
        await runtime.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run_worker(get_settings()))
