"""Isolated MVP409 API and independent production CLI Worker with labelled old synthetic tasks."""

import argparse
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
from uuid import UUID, uuid4

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--database-url", required=True)
parser.add_argument("--port", type=int, default=18151)
args = parser.parse_args()
url = urlparse(args.database_url)
if (
    url.scheme != "postgresql+asyncpg"
    or url.hostname not in {"127.0.0.1", "localhost"}
    or url.port != 15450
    or url.path != "/weekly_history_browser_20261118"
    or args.port != 18151
):
    raise SystemExit("Only the named MVP409 synthetic database and loopback18151 are allowed")
root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root / "tests/integration"))
for key in list(os.environ):
    if key.startswith("INVESTMENT_OS_"):
        del os.environ[key]
runtime = tempfile.TemporaryDirectory(prefix="mvp409-weekly-history-")
os.environ.update(
    {
        "INVESTMENT_OS_DATABASE_URL": args.database_url,
        "INVESTMENT_OS_API_WRITE_TOKEN": "synthetic-weekly-history-only",
        "INVESTMENT_OS_WORKER_POLL_SECONDS": "1",
        "INVESTMENT_OS_WORKER_READY_FILE": str(Path(runtime.name) / "worker-ready"),
        "INVESTMENT_OS_SECRET_STORE_KEY": base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode(),
        "INVESTMENT_OS_SECRET_STORE_PATH": str(Path(runtime.name) / "secrets.json"),
    }
)
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from test_complete_weekly import enable, setup  # noqa: E402
from test_weekly_task_history import append_history  # noqa: E402

from investment_os.application.complete_weekly import CompleteWeeklySave  # noqa: E402
from investment_os.application.opportunities import FunnelQuery  # noqa: E402
from investment_os.application.opportunity_schedule import WeeklySave  # noqa: E402
from investment_os.infrastructure.complete_weekly import SqlCompleteWeekly  # noqa: E402
from investment_os.infrastructure.opportunity_schedule import SqlWeeklyFunnel  # noqa: E402
from investment_os.infrastructure.persistence.models import TaskRunRecord  # noqa: E402
from investment_os.infrastructure.weekly_task_history import SqlWeeklyTaskHistory  # noqa: E402

command.upgrade(Config("alembic.ini"), "head")
(root / ".runtime").mkdir(exist_ok=True)


async def seed():
    engine = create_async_engine(args.database_url)
    try:
        fixture_path = root / ".runtime/mvp409-browser-fixture.json"
        if fixture_path.exists():
            recorded = json.loads(fixture_path.read_text(encoding="utf-8"))
            identifiers = {
                UUID(row[key])
                for row in recorded["protocols"].values()
                for key in ("oldest_failed_id", "skipped_id")
            }
            async with engine.connect() as connection:
                existing = set(
                    await connection.scalars(
                        select(TaskRunRecord.id).where(TaskRunRecord.id.in_(identifiers))
                    )
                )
            if existing != identifiers:
                raise RuntimeError("Recorded synthetic fixture does not match this database")
            if all("cli_schedule_id" in row for row in recorded["protocols"].values()):
                return
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            for protocol, row in recorded["protocols"].items():
                store = (
                    SqlWeeklyFunnel(sessions) if protocol == "1.0" else SqlCompleteWeekly(sessions)
                )
                current = next(
                    item
                    for item in (await store.overview()).configurations
                    if str(item.schedule_id) == row["schedule_id"]
                )
                model = WeeklySave if protocol == "1.0" else CompleteWeeklySave
                value = model(
                    request_id=uuid4(),
                    schedule_id=uuid4(),
                    expected_version=0,
                    name="Synthetic independent CLI Worker audit",
                    venue=current.venue,
                    funnel_run_id=current.template_run_id,
                    calendar_import_id=current.calendar_import_id,
                    coverage_start=current.coverage_start,
                    coverage_end=current.coverage_end,
                    complete_calendar_acknowledgement=True,
                    local_only_acknowledgement=True,
                )
                saved = await store.save(value)
                await enable(store, saved)
                prefix = "weekly-local:" if protocol == "1.0" else "weekly-complete:"
                async with sessions() as session:
                    count = await session.scalar(
                        select(func.count())
                        .select_from(TaskRunRecord)
                        .where(TaskRunRecord.task_name.startswith(prefix))
                    )
                row["cli_schedule_id"] = str(saved.schedule_id)
                row["expected_count"] = count + 1
            recorded["scope"] = (
                "104_SEEDED_OLD_TASKS_RUNTIME_HARNESS_HISTORY_AND_NEW_INDEPENDENT_CLI_RECORDS"
            )
            fixture_path.write_text(json.dumps(recorded), encoding="utf-8")
            return
        sessions, store, complete_command, config, runner, _ = await setup(engine, 2)
        await enable(store, config)
        records = {}
        complete_ids = await append_history(sessions, config, complete_command, "2.0", 52, False)
        query = FunnelQuery.model_validate(
            config.template.model_dump(exclude={"schema_version", "snapshot_id", "snapshot_hash"})
        )
        query = query.model_copy(update={"request_id": uuid4()})
        original = await runner.service.funnel.run(query)
        local = SqlWeeklyFunnel(sessions)
        local_command = WeeklySave.model_validate(
            complete_command.model_dump(exclude={"schema_version"})
        ).model_copy(
            update={
                "request_id": uuid4(),
                "schedule_id": uuid4(),
                "funnel_run_id": original.run_id,
                "name": "Synthetic local history worker",
            }
        )
        saved = await local.save(local_command)
        await enable(local, saved)
        local_ids = await append_history(sessions, saved, local_command, "1.0", 52, False)
        for protocol, ids, schedule in [
            ("1.0", local_ids, saved.schedule_id),
            ("2.0", complete_ids, config.schedule_id),
        ]:
            oldest = min(ids[1:], key=str)
            details = await SqlWeeklyTaskHistory(sessions, protocol).task(oldest)
            records[protocol] = {
                "oldest_failed_id": str(oldest),
                "old_revision_name": details.provenance.name,
                "skipped_id": str(ids[0]),
                "schedule_id": str(schedule),
                "seeded_count": 52,
                "cli_schedule_id": str(schedule),
                "expected_count": 53,
            }
        (root / ".runtime/mvp409-browser-fixture.json").write_text(
            json.dumps(
                {
                    "protocols": records,
                    "scope": "SYNTHETIC_104_SEEDED_OLD_TASKS_PLUS_PRODUCTION_WORKER_RECORDS",
                }
            ),
            encoding="utf-8",
        )
    finally:
        await engine.dispose()


asyncio.run(seed())
log = (root / ".runtime/mvp409-independent-cli-worker.log").open("a", encoding="utf-8")
worker = subprocess.Popen(
    [sys.executable, "-m", "investment_os.worker"],
    env=os.environ.copy(),
    stdout=log,
    stderr=subprocess.STDOUT,
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
)
(root / ".runtime/mvp409-worker-process.json").write_text(
    json.dumps(
        {
            "pid": worker.pid,
            "command": "python -m investment_os.worker",
            "scope": "OWN_SYNTHETIC_15450",
        }
    ),
    encoding="utf-8",
)
try:
    import uvicorn

    uvicorn.run(
        "investment_os.api.bootstrap:app",
        host="127.0.0.1",
        port=args.port,
        access_log=False,
        log_level="warning",
    )
finally:
    worker.terminate()
    worker.wait(timeout=10)
    log.close()
    runtime.cleanup()
