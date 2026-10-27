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


async def test_slow_analysis_does_not_block_calendar_readiness_or_start_duplicate_dispatch(
    tmp_path,
):
    import asyncio

    from investment_os.worker.main import WorkerRuntime

    started, release, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Probe(StubProbe):
        async def close(self):
            closed.set()

    class Analysis:
        calls = 0

        async def dispatch_due(self, *, now):
            self.calls += 1
            started.set()
            await release.wait()

    class Calendar:
        calls = 0

        async def dispatch_due(self, *, now):
            self.calls += 1

    calendar, analysis = Calendar(), Analysis()
    runtime = WorkerRuntime(
        probe=Probe(True),
        ready_file=tmp_path / "ready",
        scheduler=calendar,
        scheduler_engine=None,
        analysis=analysis,
    )
    assert await runtime.run_once() is True
    await asyncio.wait_for(started.wait(), timeout=1)
    assert await asyncio.wait_for(runtime.run_once(), timeout=1) is True
    assert analysis.calls == 1 and calendar.calls == 2
    await runtime.close()
    assert closed.is_set() and runtime._analysis_task.cancelled()
