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
parser.add_argument("--port", type=int, default=18129)
args = parser.parse_args()
url = urlparse(args.database_url)
if (
    url.scheme != "postgresql+asyncpg"
    or url.hostname not in {"127.0.0.1", "localhost"}
    or url.port != 15446
    or url.path not in {
        "/investment_os_mvp404_browser_20261105",
        "/investment_os_mvp404_browser_resume_20261105",
    }
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
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from analysis_numeric_fixture import seed_numeric  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

command.upgrade(Config("alembic.ini"), "head")
(root / ".runtime").mkdir(exist_ok=True)


async def seed():
    engine = create_async_engine(args.database_url)
    try:
        ids, _ = await seed_numeric(engine)
        (root / ".runtime" / "mvp404-browser-fixture.json").write_text(
            json.dumps(
                {
                    "ids": {key: str(value) for key, value in ids.items()},
                    "scope": "SYNTHETIC_LOCAL_NO_NETWORK_OR_MODELS",
                }
            ),
            encoding="utf-8",
        )
    finally:
        await engine.dispose()


asyncio.run(seed())
log = (root / ".runtime" / "mvp404-browser-worker.log").open("w", encoding="utf-8")
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
