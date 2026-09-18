import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# fmt: off
LOCAL_TEST_DATABASE_URL = (
    "postgresql+asyncpg://investment_os:"
    "local-development-only@localhost:5432/investment_os"
)
# fmt: on
TEST_DATABASE_URL = os.getenv("INVESTMENT_OS_TEST_DATABASE_URL", LOCAL_TEST_DATABASE_URL)


@pytest.fixture(scope="session")
def migrated_database_url() -> Iterator[str]:
    previous = os.environ.get("INVESTMENT_OS_DATABASE_URL")
    os.environ["INVESTMENT_OS_DATABASE_URL"] = TEST_DATABASE_URL
    command.upgrade(Config("alembic.ini"), "head")
    yield TEST_DATABASE_URL
    if previous is None:
        os.environ.pop("INVESTMENT_OS_DATABASE_URL", None)
    else:
        os.environ["INVESTMENT_OS_DATABASE_URL"] = previous


@pytest_asyncio.fixture
async def database_engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_database_url, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def clean_database(database_engine: AsyncEngine) -> AsyncIterator[None]:
    async with database_engine.begin() as connection:
        table_names = list(
            (
                await connection.execute(
                    text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                    )
                )
            ).scalars()
        )
        if table_names:
            quoted = ", ".join(f'"{name}"' for name in table_names)
            await connection.execute(text(f"TRUNCATE TABLE {quoted} CASCADE"))
    yield
