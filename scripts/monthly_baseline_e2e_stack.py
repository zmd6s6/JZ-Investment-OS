"""Dedicated local monthly API/production Worker with synthetic local facts, no model server."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--database-url", required=True)
parser.add_argument("--port", type=int, default=18149)
args = parser.parse_args()
url = urlparse(args.database_url)
if (
    url.scheme != "postgresql+asyncpg"
    or url.hostname not in {"127.0.0.1", "localhost"}
    or url.port != 15450
    or url.path != "/monthly_baseline_browser_20261117"
):
    raise SystemExit("Only the named disposable monthly loopback database is allowed")
root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root / "tests" / "integration"))
for key in list(os.environ):
    if key.startswith("INVESTMENT_OS_"):
        del os.environ[key]
runtime = tempfile.TemporaryDirectory(prefix="mvp404-monthly-synthetic-")
os.environ.update(
    {
        "INVESTMENT_OS_DATABASE_URL": args.database_url,
        "INVESTMENT_OS_API_WRITE_TOKEN": "synthetic-monthly-only",
        "INVESTMENT_OS_WORKER_POLL_SECONDS": "1",
        "INVESTMENT_OS_WORKER_READY_FILE": str(Path(runtime.name) / "worker-ready"),
    }
)
from datetime import UTC, datetime, timedelta  # noqa: E402
from uuid import uuid4  # noqa: E402

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from test_monthly_review_pipeline import setup  # noqa: E402

from investment_os.application.calendar_product import (  # noqa: E402
    CalendarImportCommand,
    CalendarProductService,
)
from investment_os.infrastructure.calendar_product import SqlCalendarProduct  # noqa: E402

command.upgrade(Config("alembic.ini"), "head")
(root / ".runtime").mkdir(exist_ok=True)


async def seed():
    engine = create_async_engine(args.database_url)
    try:
        fixture = root / ".runtime" / "mvp404-baseline-browser-fixture.json"
        if fixture.exists():
            recorded = json.loads(fixture.read_text(encoding="utf-8"))
            async with engine.connect() as connection:
                portfolio_exists = await connection.scalar(
                    text("SELECT EXISTS(SELECT 1 FROM portfolio WHERE id=:id)"),
                    {"id": recorded["ids"]["portfolio"]},
                )
                schedule_ids = set(
                    str(identifier)
                    for identifier in await connection.scalars(
                        text("SELECT id FROM monthly_configuration")
                    )
                )
            if portfolio_exists and set(recorded["schedules"].values()) <= schedule_ids:
                return  # Restart the same synthetic chain with all immutable history intact.
            raise RuntimeError("Existing fixture does not match this dedicated database")
        sessions, service, _, base, ids = await setup(engine)
        previous_end = base.coverage_start - timedelta(days=1)
        previous_start = previous_end.replace(day=1)
        earlier_start = (previous_start - timedelta(days=1)).replace(day=1)
        calendar = await CalendarProductService(SqlCalendarProduct(sessions)).import_calendar(
            CalendarImportCommand(
                request_id=uuid4(),
                expected_version=1,
                venue="SSE",
                source_name="explicit synthetic open closed open monthly coverage",
                source_version="baseline-audit",
                confirmed_source=True,
                csv_text=f"business_date,close_at\n{earlier_start},15:00\n{base.coverage_start},15:00\n",
            )
        )
        schedules = {}
        for name, start in (
            ("首次实际捕获", previous_start),
            ("跨闭市保留实际基线", earlier_start),
        ):
            value = base.model_copy(
                update={
                    "request_id": uuid4(),
                    "schedule_id": uuid4(),
                    "name": name,
                    "coverage_start": start,
                    "calendar_import_id": calendar.import_id,
                    "valid_until": datetime.now(UTC) + timedelta(days=2),
                }
            )
            prepared = await service.preview(value, datetime.now(UTC))
            saved = await service.save(value, prepared.content_hash)
            assert not saved.enabled
            schedules[name] = str(saved.schedule_id)
        (root / ".runtime" / "mvp404-baseline-browser-fixture.json").write_text(
            json.dumps(
                {
                    "ids": {key: str(value) for key, value in ids.items()},
                    "schedules": schedules,
                    "scope": "SYNTHETIC_LOCAL_NO_NETWORK_OR_MODELS",
                }
            ),
            encoding="utf-8",
        )
    finally:
        await engine.dispose()


asyncio.run(seed())
log = (root / ".runtime" / f"mvp404-browser-worker-{args.port}.log").open("w", encoding="utf-8")
worker = subprocess.Popen(
    [sys.executable, "-m", "investment_os.worker"],
    env=os.environ.copy(),
    stdout=log,
    stderr=subprocess.STDOUT,
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
)
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
    worker.terminate()
    worker.wait(timeout=10)
    log.close()
    runtime.cleanup()
