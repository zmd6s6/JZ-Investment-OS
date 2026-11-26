"""Dedicated synthetic PostgreSQL/API and actual CLI Worker monthly recovery stack."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--database-url", required=True)
parser.add_argument("--port", type=int, default=18164)
args = parser.parse_args()
url = urlparse(args.database_url)
if (
    url.scheme != "postgresql+asyncpg"
    or url.hostname not in {"127.0.0.1", "localhost"}
    or url.path != "/mvp404_recovery_synthetic"
    or args.port != 18164
):
    raise SystemExit("Only the dedicated synthetic loopback recovery database and port are allowed")
root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root / "tests" / "integration"))
for key in list(os.environ):
    if key.startswith("INVESTMENT_OS_"):
        del os.environ[key]
runtime = tempfile.TemporaryDirectory(prefix="mvp404-recovery-synthetic-")
os.environ.update(
    {
        "INVESTMENT_OS_DATABASE_URL": args.database_url,
        "INVESTMENT_OS_API_WRITE_TOKEN": "synthetic-monthly-only",
        "INVESTMENT_OS_WORKER_POLL_SECONDS": "1",
        "INVESTMENT_OS_WORKER_READY_FILE": str(Path(runtime.name) / "worker-ready"),
    }
)
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from test_monthly_review_pipeline import enable, setup  # noqa: E402

from investment_os.application.calendar_product import (  # noqa: E402
    CalendarImportCommand,
    CalendarProductService,
)
from investment_os.infrastructure.calendar_product import SqlCalendarProduct  # noqa: E402

command.upgrade(Config("alembic.ini"), "head")
(root / ".runtime").mkdir(exist_ok=True)
log = (root / ".runtime" / "mvp404-recovery-worker.log").open("w", encoding="utf-8")


def start_worker():
    return subprocess.Popen(
        [sys.executable, "-m", "investment_os.worker"],
        env=os.environ.copy(),
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def stop_worker(process):
    process.terminate()
    process.wait(timeout=10)


async def seed_authorizations_and_wait_for_real_worker():
    engine = create_async_engine(args.database_url)
    worker = None
    try:
        sessions, service, _, base, ids = await setup(engine)
        earlier_end = base.coverage_start - timedelta(days=1)
        earlier_start = earlier_end.replace(day=1)
        initial_calendar = await CalendarProductService(
            SqlCalendarProduct(sessions)
        ).import_calendar(
            CalendarImportCommand(
                request_id=uuid4(),
                expected_version=1,
                venue="SSE",
                source_name="original synthetic open monthly source",
                source_version="v2",
                confirmed_source=True,
                csv_text=f"business_date,close_at\n{earlier_start},15:00\n{base.coverage_start},15:00\n{base.coverage_end},15:00\n",
            )
        )
        base = base.model_copy(update={"calendar_import_id": initial_calendar.import_id})
        first = base.model_copy(
            update={"coverage_start": earlier_start, "coverage_end": earlier_end}
        )
        await enable(service, first)
        worker = start_worker()
        for _ in range(90):
            reports = await service.reports(base.schedule_id)
            if len(reports) == 1:
                break
            if worker.poll() is not None:
                raise RuntimeError("Initial production Worker exited")
            await asyncio.sleep(1)
        else:
            raise RuntimeError("Actual Worker did not commit original successful month")
        stop_worker(worker)
        worker = None
        current = (await service.configurations())[0]
        expanded = base.model_copy(
            update={
                "request_id": uuid4(),
                "expected_version": current.version,
                "coverage_start": earlier_start,
            }
        )
        await enable(service, expanded)
        replacement = await CalendarProductService(SqlCalendarProduct(sessions)).import_calendar(
            CalendarImportCommand(
                request_id=uuid4(),
                expected_version=2,
                venue="SSE",
                source_name="repaired synthetic monthly source",
                source_version="v3",
                confirmed_source=True,
                csv_text=f"business_date,close_at\n{base.coverage_start},15:00\n{base.coverage_end},15:00\n",
            )
        )
        worker = start_worker()
        for _ in range(90):
            failed = next((task for task in await service.runs() if task.status == "FAILED"), None)
            if failed is not None and failed.attempt == 3:
                break
            if worker.poll() is not None:
                raise RuntimeError("Recovery production Worker exited")
            await asyncio.sleep(1)
        else:
            raise RuntimeError("Actual Worker did not exhaust three failed source attempts")
        fixture = {
            "schedule_id": str(base.schedule_id),
            "portfolio_id": str(ids["portfolio"]),
            "calendar_import_id": str(replacement.import_id),
            "report": reports[0].model_dump(mode="json"),
            "failed_task": failed.model_dump(mode="json"),
            "period_start": str(base.coverage_start),
            "scope": "SYNTHETIC_LOCAL_NO_NETWORK_OR_MODELS_REAL_CLI_WORKER",
            "seeded": "source facts and explicit authorizations only; no seeded TaskRun or report",
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        (root / ".runtime" / "mvp404-recovery-fixture.json").write_text(
            json.dumps(fixture), encoding="utf-8"
        )
        result, worker = worker, None
        return result
    finally:
        if worker is not None:
            stop_worker(worker)
        await engine.dispose()


worker = asyncio.run(seed_authorizations_and_wait_for_real_worker())
try:
    import uvicorn

    uvicorn.run(
        "investment_os.api.bootstrap:app",
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
        access_log=False,
    )
finally:
    stop_worker(worker)
    log.close()
    runtime.cleanup()
