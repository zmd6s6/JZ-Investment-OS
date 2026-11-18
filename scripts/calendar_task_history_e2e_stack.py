"""Dedicated synthetic Calendar audit API plus an independent production CLI Worker.

Reads credentials from an ignored local file, never prints them. Creates no database;
requires the separately created, named empty MVP410 database on synthetic port15450.
"""

import asyncio
import base64
import json
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root / "tests/integration"))
config = json.loads((root / ".runtime/calendar-db.json").read_text(encoding="utf-8"))
url = config["e2e"]
parsed = urlparse(url)
if (
    parsed.hostname not in {"127.0.0.1", "localhost"}
    or parsed.port != 15450
    or parsed.path != "/mvp410_e2e_20261118"
):
    raise SystemExit("Only the independently created MVP410 synthetic database is allowed")
for key in list(os.environ):
    if key.startswith("INVESTMENT_OS_"):
        del os.environ[key]
runtime = tempfile.TemporaryDirectory(prefix="mvp410-calendar-history-")
os.environ.update(
    {
        "INVESTMENT_OS_DATABASE_URL": url,
        "INVESTMENT_OS_API_WRITE_TOKEN": "synthetic-calendar-history-only",
        "INVESTMENT_OS_WORKER_POLL_SECONDS": "1",
        "INVESTMENT_OS_WORKER_READY_FILE": str(Path(runtime.name) / "worker-ready"),
        "INVESTMENT_OS_SECRET_STORE_KEY": base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode(),
        "INVESTMENT_OS_SECRET_STORE_PATH": str(Path(runtime.name) / "secrets.json"),
    }
)
from alembic import command as migrate  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from test_calendar_product_persistence import command, enable, setup  # noqa: E402
from test_calendar_task_history import history_setup  # noqa: E402

from investment_os.infrastructure.persistence.models import TaskRunRecord  # noqa: E402

migrate.upgrade(Config("alembic.ini"), "head")
fixture_path = root / ".runtime/mvp410-browser-fixture.json"


async def seed():
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            count = await connection.scalar(select(func.count()).select_from(TaskRunRecord))
        if count:
            if not fixture_path.exists():
                raise RuntimeError(
                    "Existing database is not an identified fixture; refusing to change it"
                )
            return json.loads(fixture_path.read_text(encoding="utf-8"))
        _, service, config, ids = await history_setup(engine, 102)
        source_b = await service.import_calendar(
            command(version=config.version, days="2025-01-01,15:00", source="SOURCE_B_CLI_WORKER")
        )
        source_b = await enable(service, source_b)
        record = {
            "seeded_old_failed_tasks": 102,
            "seeded_other_namespace_tasks": 105,
            "old_failed_id": str(ids[0]),
            "source_a_import_id": str(config.import_id),
            "source_b_import_id": str(source_b.import_id),
            "source_b_version": source_b.version,
            "scope": "SYNTHETIC_SEEDED_OLD_FAILURES_SEPARATE_FROM_NEW_INDEPENDENT_CLI_REPORT",
        }
        fixture_path.write_text(json.dumps(record), encoding="utf-8")
        return record
    finally:
        await engine.dispose()


record = asyncio.run(seed())
log = (root / ".runtime/mvp410-cli-worker.log").open("a", encoding="utf-8")
worker = subprocess.Popen(
    [sys.executable, "-m", "investment_os.worker"],
    env=os.environ.copy(),
    stdout=log,
    stderr=subprocess.STDOUT,
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
)
(root / ".runtime/mvp410-process.json").write_text(
    json.dumps(
        {
            "worker_pid": worker.pid,
            "api_pid": os.getpid(),
            "worker_command": "python -m investment_os.worker",
            "api_port": 18155,
            "database_port": 15450,
        }
    ),
    encoding="utf-8",
)


async def wait_for_cli_report():
    engine = create_async_engine(url)
    try:
        sessions, service = setup(engine)
        for _ in range(100):
            async with sessions() as session:
                task = await session.scalar(
                    select(TaskRunRecord).where(
                        TaskRunRecord.idempotency_key
                        == f"calendar-status:SSE:2025-01-01:{record['source_b_import_id']}",
                        TaskRunRecord.status == "SUCCEEDED",
                    )
                )
            if task:
                detail = await service.task(task.id)
                if detail.report_json and detail.report_hash:
                    record.update(
                        {
                            "cli_task_id": str(task.id),
                            "cli_report_event_id": str(detail.report_event_id),
                            "original_report_hash": detail.report_hash,
                            "original_source_hash": detail.source.calendar_hash,
                        }
                    )
                    if not record.get("source_c_import_id"):
                        current = (await service.overview()).configurations[0]
                        changed = await service.import_calendar(
                            command(
                                version=current.version,
                                days="2025-01-01,15:00",
                                source="SOURCE_C_CURRENT_PAUSED",
                            )
                        )
                        record["source_c_import_id"] = str(changed.import_id)
                    fixture_path.write_text(json.dumps(record), encoding="utf-8")
                    return
            await asyncio.sleep(0.2)
        raise RuntimeError("Independent CLI Worker did not create the expected verified report")
    finally:
        await engine.dispose()


try:
    asyncio.run(wait_for_cli_report())
    print(
        "MVP410 synthetic API18155 ready;102 seeded FAILED audit rows,105 other tasks,"
        "1 independent CLI-produced report. Current pointerC differs from originalA/B.",
        flush=True,
    )
    import uvicorn

    uvicorn.run(
        "investment_os.api.bootstrap:app",
        host="127.0.0.1",
        port=18155,
        access_log=False,
        log_level="warning",
    )
finally:
    worker.terminate()
    worker.wait(timeout=10)
    log.close()
    runtime.cleanup()
