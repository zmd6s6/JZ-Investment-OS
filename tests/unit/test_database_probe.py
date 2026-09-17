from types import TracebackType
from typing import Any

import pytest

from investment_os.infrastructure import database


class FakeConnection:
    async def execute(self, _: Any) -> None:
        return None


class FakeConnectionContext:
    def __init__(self, *, error: bool = False) -> None:
        self._error = error

    async def __aenter__(self) -> FakeConnection:
        if self._error:
            raise OSError("synthetic connection failure")
        return FakeConnection()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class FakeEngine:
    def __init__(self, *, error: bool = False) -> None:
        self._error = error
        self.disposed = False

    def connect(self) -> FakeConnectionContext:
        return FakeConnectionContext(error=self._error)

    async def dispose(self) -> None:
        self.disposed = True


@pytest.mark.asyncio
async def test_database_probe_reports_ready_and_disposes(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = FakeEngine()
    monkeypatch.setattr(database, "create_async_engine", lambda *args, **kwargs: engine)
    probe = database.DatabaseReadinessProbe("postgresql+asyncpg://synthetic")

    result = await probe.check()
    await probe.close()

    assert result.ready is True
    assert result.detail == "database_ready"
    assert engine.disposed is True


@pytest.mark.asyncio
async def test_database_probe_sanitizes_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine(error=True)
    monkeypatch.setattr(database, "create_async_engine", lambda *args, **kwargs: engine)
    probe = database.DatabaseReadinessProbe("postgresql+asyncpg://synthetic")

    result = await probe.check()

    assert result.ready is False
    assert result.detail == "database_unavailable"
