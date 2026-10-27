"""Synthetic-only pause-race fixture; no production endpoint or runtime fault option."""

import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "src"))
database = os.environ.get("E2E_CALENDAR_FIXTURE_DATABASE", "")
if not re.fullmatch(r"investment_os_mvp401_browser_[a-z_]+", database):
    raise SystemExit("explicit MVP401 synthetic database name is required")
for name in list(os.environ):
    if name.startswith("INVESTMENT_OS_"):
        del os.environ[name]

from sqlalchemy import select  # noqa: E402

from investment_os.application.calendar_product import CalendarModeCommand  # noqa: E402
from investment_os.application.schedule import MarketVenue  # noqa: E402
from investment_os.infrastructure.calendar_product import SqlCalendarProduct  # noqa: E402
from investment_os.infrastructure.database import (  # noqa: E402
    create_database_engine,
    create_session_factory,
)
from investment_os.infrastructure.persistence.calendar_models import (  # noqa: E402
    CalendarConfigurationRecord,
    CalendarImportRecord,
)
from investment_os.infrastructure.persistence.jobs import ReliableJobExecutor  # noqa: E402
from investment_os.infrastructure.settings import Settings  # noqa: E402
from investment_os.worker.main import WorkerRuntime, run_worker  # noqa: E402


async def main():
    with tempfile.TemporaryDirectory(prefix="mvp401-race-") as runtime_dir:
        settings = Settings(
            database_url=(
                "postgresql+asyncpg://investment_os:synthetic-e2e-only@"  # pragma: allowlist secret
                f"127.0.0.1:15438/{database}"
            ),
            worker_poll_seconds=1,
            worker_ready_file=Path(runtime_dir) / "worker-ready",
        )
        if sys.argv[1] == "loop":
            await run_worker(settings)
            return
        if sys.argv[1] == "loop-once":
            runtime = WorkerRuntime.from_settings(settings)
            try:
                await runtime.run_once()
            finally:
                await runtime.close()
            return
        if sys.argv[1] != "pause-race":
            raise ValueError("unknown fixture action")
        engine = create_database_engine(settings.database_url)
        sessions = create_session_factory(engine)
        original = ReliableJobExecutor.execute
        runtime = WorkerRuntime.from_settings(settings)
        try:
            async with sessions() as session:
                config = await session.scalar(
                    select(CalendarConfigurationRecord).where(
                        CalendarConfigurationRecord.venue == "SZSE"
                    )
                )
                if config is None or not config.enabled:
                    raise ValueError("explicit enabled SZSE fixture configuration is required")
                record = await session.get(CalendarImportRecord, config.active_import_id)
                if record is None or record.source_version != "synthetic-recovery-A":
                    raise ValueError("only the named synthetic A source can be paused")

            async def pause_then_execute(executor, **kwargs):
                if kwargs["task_name"] != "calendar_status_SZSE":
                    raise ValueError("fixture cannot target another market task")
                await SqlCalendarProduct(sessions).set_mode(
                    MarketVenue.SZSE,
                    CalendarModeCommand(
                        request_id=uuid4(),
                        expected_version=config.version,
                        enabled=False,
                        status_only_acknowledgement=True,
                    ),
                )
                return await original(executor, **kwargs)

            ReliableJobExecutor.execute = pause_then_execute
            await runtime.run_once()
        finally:
            ReliableJobExecutor.execute = original
            await runtime.close()
            await engine.dispose()


asyncio.run(main())
