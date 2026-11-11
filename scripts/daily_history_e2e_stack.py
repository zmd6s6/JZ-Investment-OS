"""Dedicated synthetic 52-configuration production API/Worker browser fixture."""

import argparse
import asyncio
import base64
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--database-url", required=True)
parser.add_argument("--port", type=int, default=18143)
parser.add_argument(
    "--resume",
    action="store_true",
    help="Restart this exact seeded synthetic stack without reseeding",
)
args = parser.parse_args()
url = urlparse(args.database_url)
if (
    url.scheme != "postgresql+asyncpg"
    or url.hostname != "127.0.0.1"
    or url.port != 15449
    or re.fullmatch(r"/investment_os_mvp406_browser_[a-z0-9_]+", url.path) is None
):
    raise SystemExit("Only dedicated MVP406 synthetic database permitted")
root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root / "tests" / "integration"))
for key in list(os.environ):
    if key.startswith("INVESTMENT_OS_"):
        del os.environ[key]
runtime = tempfile.TemporaryDirectory(prefix="mvp406-synthetic-")
os.environ.update(
    {
        "INVESTMENT_OS_DATABASE_URL": args.database_url,
        "INVESTMENT_OS_SECRET_STORE_KEY": base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode(),
        "INVESTMENT_OS_SECRET_STORE_PATH": str(Path(runtime.name) / "secrets.json"),
        "INVESTMENT_OS_API_WRITE_TOKEN": "synthetic-mvp406-only",
        "INVESTMENT_OS_WORKER_POLL_SECONDS": "1",
        "INVESTMENT_OS_WORKER_READY_FILE": str(Path(runtime.name) / "worker-ready"),
    }
)
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from analysis_numeric_fixture import seed_numeric  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from investment_os.application.calendar_product import (  # noqa: E402
    CalendarImportCommand,
    CalendarProductService,
)
from investment_os.application.daily_runtime import (  # noqa: E402
    DailyMode,
    DailyRuntimeService,
    DailySave,
)
from investment_os.infrastructure.calendar_product import SqlCalendarProduct  # noqa: E402
from investment_os.infrastructure.daily_runtime_setup import SqlDailySetup  # noqa: E402
from investment_os.infrastructure.daily_runtime_store import SqlDailyRuntimeStore  # noqa: E402

command.upgrade(Config("alembic.ini"), "head")
(root / ".runtime").mkdir(exist_ok=True)


async def seed():
    engine = create_async_engine(args.database_url)
    try:
        if args.resume:
            async with engine.connect() as connection:
                count = await connection.scalar(text("SELECT count(*) FROM daily_configuration"))
                modes = (
                    (
                        await connection.execute(
                            text("SELECT DISTINCT mode FROM daily_authorization_revision")
                        )
                    )
                    .scalars()
                    .all()
                )
                if (
                    count != 52
                    or modes != ["LOCAL_STATUS_ONLY"]
                    or not (root / ".runtime/mvp406-browser-fixture.json").is_file()
                ):
                    raise SystemExit("Resume requires this exact local-only synthetic fixture")
            return
        ids, _ = await seed_numeric(engine)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        close = (datetime.now(UTC) + timedelta(seconds=100)).replace(second=0, microsecond=0)
        market_close = close.astimezone(ZoneInfo("Asia/Shanghai"))
        calendar = await CalendarProductService(SqlCalendarProduct(sessions)).import_calendar(
            CalendarImportCommand(
                request_id=uuid4(),
                expected_version=0,
                venue="SSE",
                source_name="406显式合成日历",
                source_version="v1",
                confirmed_source=True,
                csv_text=f"business_date,close_at\n{market_close.date()},{market_close:%H:%M}\n",
            )
        )
        setup = SqlDailySetup(sessions, None, None)
        store = SqlDailyRuntimeStore(sessions, setup)
        service = DailyRuntimeService(setup, store)
        for index in range(1, 53):
            item = DailySave(
                request_id=uuid4(),
                schedule_id=UUID(int=index),
                expected_version=0,
                name=f"406合成每日{index:03}",
                mode="LOCAL_STATUS_ONLY",
                market="SSE",
                portfolio_id=ids["portfolio"],
                portfolio_instrument_ids=(ids["instrument"],),
                watchlist_instrument_ids=(),
                calendar_import_id=calendar.import_id,
                coverage_start=market_close.date(),
                coverage_end=market_close.date(),
                frequency="DAILY_AFTER_EXPLICIT_CLOSE",
                missed_run_policy="LOCAL_REPORT_ONLY_NO_RESEARCH",
                quote_source_name="synthetic-205-reference",
                evidence_source_names=(),
                retention_days=7,
                valid_from=datetime.now(UTC) - timedelta(minutes=1),
                valid_until=datetime.now(UTC) + timedelta(days=1),
                model_profiles={},
                data_profile_ids=(),
                limits=dict(
                    currency="NONE", task_tokens=0, day_tokens=0, task_cost="0", day_cost="0"
                ),
                pause_method="DAILY_UI_PAUSE_OR_REVOKE",
                complete_calendar_acknowledgement=True,
                scope_acknowledgement=True,
                local_only_acknowledgement=True,
                model_egress_acknowledgement=False,
                cost_acknowledgement=False,
            )
            saved = await service.save(item)
            await store.mode(
                item.schedule_id,
                DailyMode(
                    request_id=uuid4(),
                    expected_version=saved.version,
                    action="ENABLE",
                    confirmed=True,
                ),
            )
        (root / ".runtime/mvp406-browser-fixture.json").write_text(
            json.dumps(
                {
                    "tail": str(UUID(int=52)),
                    "oldest": str(UUID(int=1)),
                    "count": 52,
                    "close": close.isoformat(),
                    "external_calls": 0,
                    "model_calls": 0,
                }
            ),
            encoding="utf-8",
        )
    finally:
        await engine.dispose()


asyncio.run(seed())
log = (root / ".runtime/mvp406-worker.log").open("w", encoding="utf-8")
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
