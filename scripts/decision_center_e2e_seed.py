"""Reset only the expressly named disposable MVP301 browser database and seed real ports."""

import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "tests" / "integration"))
from decision_center_fixture import seed_center  # noqa: E402


async def seed(url: str) -> dict:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            tables = (
                (
                    await connection.execute(
                        text(
                            "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                            "AND tablename <> 'alembic_version'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            quoted = ",".join('"' + table.replace('"', '""') + '"' for table in tables)
            if quoted:
                await connection.execute(text(f"TRUNCATE {quoted} CASCADE"))
        return await seed_center(engine, decision_count=3)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    url = os.environ.get("INVESTMENT_OS_DATABASE_URL", "")
    parsed = urlparse(url)
    if (
        parsed.hostname != "127.0.0.1"
        or parsed.port != 15444
        or parsed.path != "/investment_os_mvp301_browser"
    ):
        raise SystemExit(
            "Refusing any database except the named disposable MVP301 browser database"
        )
    os.chdir(root)
    command.upgrade(Config("alembic.ini"), "head")
    result = asyncio.run(seed(url))
    folder = root / ".runtime"
    folder.mkdir(exist_ok=True)
    (folder / "mvp301-fixture.json").write_text(json.dumps(result, default=str), encoding="utf-8")
    print("MVP301 synthetic browser fixture ready; no owner database or provider was touched")
