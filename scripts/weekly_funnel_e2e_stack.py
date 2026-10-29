"""Disposable loopback API + production WorkerRuntime with an explicit synthetic weekly clock.

No model fixture or external data gateway is started. Never point at an Owner database.
The supplied clock affects this isolated weekly worker only, not production settings.
"""

import argparse
import asyncio
import base64
import os
import secrets
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--database-url", required=True)
parser.add_argument("--port", type=int, default=18113)
parser.add_argument("--synthetic-now", required=True)
args = parser.parse_args()
url = urlparse(args.database_url)
if (
    url.scheme != "postgresql+asyncpg"
    or url.hostname not in {"127.0.0.1", "localhost"}
    or url.port != 15441
    or not url.path.endswith("_weekly_synthetic")
    or args.port != 18113
):
    raise SystemExit(
        "Only the explicit MVP402 disposable loopback weekly database/ports are allowed"
    )
synthetic_now = datetime.fromisoformat(args.synthetic_now)
if synthetic_now.utcoffset() is None:
    raise SystemExit("An explicit timezone-aware synthetic clock is required")
root = Path(__file__).resolve().parents[1]
os.chdir(root)
for key in list(os.environ):
    if key.startswith("INVESTMENT_OS_"):
        del os.environ[key]
temporary = tempfile.TemporaryDirectory(prefix="mvp402-weekly-synthetic-")
os.environ.update(
    {
        "INVESTMENT_OS_DATABASE_URL": args.database_url,
        "INVESTMENT_OS_SECRET_STORE_KEY": base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode(),
        "INVESTMENT_OS_SECRET_STORE_PATH": str(Path(temporary.name) / "secrets.json"),
        "INVESTMENT_OS_API_WRITE_TOKEN": "synthetic-mvp402-only",
    }
)
from alembic import command  # noqa: E402 - isolated settings must precede application imports
from alembic.config import Config  # noqa: E402

from investment_os.infrastructure.database import (  # noqa: E402
    DatabaseReadinessProbe,
    create_database_engine,
    create_session_factory,
)
from investment_os.worker.main import WorkerRuntime  # noqa: E402
from investment_os.worker.weekly_funnel import weekly_worker  # noqa: E402

command.upgrade(Config(str(root / "alembic.ini")), "head")
stop = threading.Event()


async def worker() -> None:
    engine = create_database_engine(args.database_url)
    runtime = WorkerRuntime(
        probe=DatabaseReadinessProbe(args.database_url),
        ready_file=Path(temporary.name) / "worker-ready",
        scheduler=None,
        scheduler_engine=engine,
        weekly=weekly_worker(create_session_factory(engine), now=lambda: synthetic_now),
    )
    try:
        while not stop.is_set():
            await runtime.run_once(now=synthetic_now)
            await asyncio.sleep(0.5)
    finally:
        await runtime.close()


thread = threading.Thread(target=lambda: asyncio.run(worker()), daemon=True)
thread.start()
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
    stop.set()
    thread.join(timeout=10)
    temporary.cleanup()
