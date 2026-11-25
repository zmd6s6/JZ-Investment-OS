"""Read-only hash/count evidence, restricted to dedicated MVP412 loopback synthetic DB."""

import asyncio
import hashlib
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


async def main(config):
    url = make_url(config["browser_url"])
    if url.host not in {"localhost", "127.0.0.1"} or not (
        url.database
        and url.database.startswith("mvp412_")
        and url.database.endswith("_analysis_synthetic")
    ):
        raise SystemExit("Dedicated MVP412 loopback synthetic database required")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            result = {}
            for name in (
                "investment_thesis",
                "thesis_version",
                "thesis_version_evidence",
                "thesis_command_receipt",
                "audit_log",
                "event_log",
                "outbox_event",
                "analysis_run",
            ):
                rows = (
                    await connection.scalars(
                        text(f'SELECT to_jsonb(t)::text FROM "{name}" t ORDER BY to_jsonb(t)::text')
                    )
                ).all()
                result[name] = {
                    "count": len(rows),
                    "hash": hashlib.sha256(json.dumps(rows).encode()).hexdigest(),
                }
            print(json.dumps(result))
    finally:
        await engine.dispose()


asyncio.run(main(json.loads(Path(".runtime/mvp412-databases.json").read_text())))
