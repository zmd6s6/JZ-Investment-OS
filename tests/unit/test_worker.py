from pathlib import Path

import pytest

from investment_os.application.health import HealthCheck
from investment_os.worker.main import refresh_ready_marker


class StubProbe:
    def __init__(self, ready: bool) -> None:
        self.ready = ready

    async def check(self) -> HealthCheck:
        return HealthCheck(
            ready=self.ready,
            detail="database_ready" if self.ready else "database_unavailable",
        )


@pytest.mark.asyncio
async def test_ready_worker_creates_marker(tmp_path: Path) -> None:
    marker = tmp_path / "worker-ready"

    result = await refresh_ready_marker(StubProbe(ready=True), marker)

    assert result is True
    assert marker.is_file()


@pytest.mark.asyncio
async def test_unready_worker_removes_stale_marker(tmp_path: Path) -> None:
    marker = tmp_path / "worker-ready"
    marker.touch()

    result = await refresh_ready_marker(StubProbe(ready=False), marker)

    assert result is False
    assert not marker.exists()
