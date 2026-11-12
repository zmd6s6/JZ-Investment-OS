"""New isolated persisted Decision history behind the production API and Worker."""

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
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--database-url", required=True)
parser.add_argument("--port", type=int, default=18145)
args = parser.parse_args()
url = urlparse(args.database_url)
if (
    url.scheme != "postgresql+asyncpg"
    or url.hostname != "127.0.0.1"
    or url.port != 15449
    or re.fullmatch(r"/investment_os_mvp407_browser_[a-z0-9_]+", url.path) is None
):
    raise SystemExit("Only a new named MVP407 loopback synthetic database is permitted")
root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root / "tests/integration"))
for key in list(os.environ):
    if key.startswith("INVESTMENT_OS_"):
        del os.environ[key]
runtime = tempfile.TemporaryDirectory(prefix="mvp407-synthetic-")
os.environ.update(
    {
        "INVESTMENT_OS_DATABASE_URL": args.database_url,
        "INVESTMENT_OS_SECRET_STORE_KEY": base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode(),
        "INVESTMENT_OS_SECRET_STORE_PATH": str(Path(runtime.name) / "secrets.json"),
        "INVESTMENT_OS_API_WRITE_TOKEN": "synthetic-407-only",
        "INVESTMENT_OS_WORKER_READY_FILE": str(Path(runtime.name) / "worker-ready"),
    }
)
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from decision_center_fixture import seed_center  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from investment_os.domain.approval import DecisionApproval  # noqa: E402
from investment_os.domain.enums import ApprovalAction  # noqa: E402
from investment_os.domain.values import UtcTimestamp  # noqa: E402
from investment_os.infrastructure.decision_center import SqlDecisionCenter  # noqa: E402
from investment_os.infrastructure.decision_journal import (  # noqa: E402
    SqlAlchemyDecisionJournalWriter,
)

command.upgrade(Config("alembic.ini"), "head")
(root / ".runtime").mkdir(exist_ok=True)


async def seed():
    engine = create_async_engine(args.database_url)
    try:
        async with engine.connect() as connection:
            if await connection.scalar(text("SELECT count(*) FROM investment_decision")):
                raise SystemExit(
                    "Fixture requires a new empty database; existing history is preserved"
                )
        await seed_center(engine, decision_count=106)
        veto = await seed_center(engine, symbol="SYNTH407-VETO", strategy_version=2, veto=True)
        expired = await seed_center(
            engine,
            symbol="SYNTH407-EXPIRED",
            strategy_version=3,
            review_lifetime=-timedelta(seconds=1),
        )
        policy = await seed_center(
            engine, symbol="SYNTH407-POLICY", strategy_version=4, policy_active=False
        )
        legacy = await seed_center(engine, symbol="SYNTH407-LEGACY", strategy_version=5)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        await SqlAlchemyDecisionJournalWriter(sessions).append_approval(
            DecisionApproval(
                decision_id=legacy["decision"],
                actor_id="synthetic-legacy-human",
                action=ApprovalAction.APPROVE,
                occurred_at=UtcTimestamp(legacy["now"]),
                expires_at=UtcTimestamp(legacy["now"] + timedelta(hours=1)),
                comment="明确保留旧合成历史, 不补造中心回执",
            )
        )
        center = SqlDecisionCenter(sessions)
        tail = await center.list(offset=100)
        assert len(tail) == 10
        (root / ".runtime/mvp407-fixture.json").write_text(
            json.dumps(
                {
                    "older": [str(card.decision_id) for card in tail],
                    "count": 110,
                    "veto": str(veto["decision"]),
                    "expired": str(expired["decision"]),
                    "policy": str(policy["decision"]),
                    "legacy": str(legacy["decision"]),
                    "fixture": "synthetic-real-domain-sizer-and-immutable-journal-not-owner-data",
                    "external_calls": 0,
                    "model_calls": 0,
                }
            ),
            encoding="utf-8",
        )
    finally:
        await engine.dispose()


asyncio.run(seed())
log = (root / ".runtime/mvp407-worker.log").open("w", encoding="utf-8")
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
