"""Disposable production API with synthetic lifecycle pointers; no provider or Worker."""

import argparse
import asyncio
import base64
import json
import os
import secrets
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--database-url", required=True)
parser.add_argument("--port", type=int, default=18136)
args = parser.parse_args()
url = urlparse(args.database_url)
if (
    url.hostname not in {"127.0.0.1", "localhost"}
    or url.port != 15441
    or url.scheme != "postgresql+asyncpg"
    or not url.path.endswith("_lifecycle_e2e_synthetic")
    or args.port != 18136
):
    raise SystemExit("Only this disposable synthetic lifecycle database and port are allowed")
root = Path(__file__).resolve().parents[1]
os.chdir(root)
for key in list(os.environ):
    if key.startswith("INVESTMENT_OS_"):
        del os.environ[key]
temporary = tempfile.TemporaryDirectory(prefix="lifecycle-synthetic-")
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

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from investment_os.infrastructure.persistence.models import (  # noqa: E402
    InstrumentRecord,
    InstrumentStateRecord,
)

command.upgrade(Config(str(root / "alembic.ini")), "head")


async def seed():
    engine = create_async_engine(args.database_url)
    now = datetime.now(UTC)
    ids = []
    try:
        sessions = async_sessionmaker(engine)
        async with sessions() as session, session.begin():
            for index, (state, version) in enumerate([("WATCH", 1), ("SETUP", 2), ("BUYABLE", 1)]):
                identifier = uuid4()
                ids.append(str(identifier))
                session.add(
                    InstrumentRecord(
                        id=identifier,
                        symbol=f"SYNLC{index}",
                        exchange="SSE",
                        name=f"合成生命周期{index}",
                        asset_type="EQUITY",
                        currency="CNY",
                        created_by="synthetic",
                        correlation_id=uuid4(),
                    )
                )
                await session.flush()
                session.add(
                    InstrumentStateRecord(
                        instrument_id=identifier,
                        lifecycle_state=state,
                        version=version,
                        created_at=now - timedelta(hours=1),
                        effective_at=now + timedelta(days=1)
                        if index == 2
                        else now - timedelta(hours=1),
                        created_by="synthetic",
                        correlation_id=uuid4(),
                    )
                )
        (root / ".runtime" / "lifecycle-fixture.json").write_text(
            json.dumps({"ids": ids}), encoding="utf-8"
        )
    finally:
        await engine.dispose()


asyncio.run(seed())
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
    temporary.cleanup()
