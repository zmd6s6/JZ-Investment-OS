"""PostgreSQL readiness adapter for bootstrap services."""

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from investment_os.application.health import HealthCheck


class DatabaseReadinessProbe:
    """Own an async engine and expose a sanitized database readiness check."""

    def __init__(self, database_url: str) -> None:
        self._engine: AsyncEngine = create_async_engine(database_url, pool_pre_ping=True)

    async def check(self) -> HealthCheck:
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except (SQLAlchemyError, OSError):
            return HealthCheck(ready=False, detail="database_unavailable")
        return HealthCheck(ready=True, detail="database_ready")

    async def close(self) -> None:
        await self._engine.dispose()
