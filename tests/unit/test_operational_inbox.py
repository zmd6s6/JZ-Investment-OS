"""MVP-405: normal, failure, and boundary cases for the read-only inbox."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from investment_os.application.operational_inbox import LIMIT, degraded, pending

NOW = datetime(2026, 11, 11, tzinfo=UTC)


class Center:
    def __init__(self, state="PENDING_APPROVAL", veto=False, expired=False):
        self.id = uuid4()
        self.state, self.veto, self.expired = state, veto, expired
        self.calls = []

    async def list(self):
        self.calls.append("list")
        return (
            SimpleNamespace(
                decision_id=self.id,
                state=self.state,
                created_at=NOW,
                symbol="TEST",
                action="BUY",
            ),
        )

    async def get(self, decision_id):
        self.calls.append("get")
        assert decision_id == self.id
        return SimpleNamespace(
            decision=SimpleNamespace(state=self.state, blockers=("VETO",) if self.veto else ()),
            allowed_actions=("APPROVE",) if not self.veto else (),
            approval_expires_at=NOW - timedelta(seconds=1) if self.expired else None,
            lineage={"risk_veto": self.veto},
        )


@pytest.mark.asyncio
async def test_pending_normal_read_only():
    center = Center()
    result = await pending(center, NOW)
    assert result.state == "AVAILABLE"
    assert result.items[0].detail_url == f"/decisions?decision_id={center.id}"
    assert center.calls == ["list", "get"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state,veto,expired",
    [
        ("REJECTED", False, False),
        ("PENDING_APPROVAL", True, False),
        ("PENDING_APPROVAL", False, True),
    ],
)
async def test_pending_rejects_ineligible_or_expired(state, veto, expired):
    result = await pending(Center(state, veto, expired), NOW)
    assert result.state == "EMPTY"


@pytest.mark.asyncio
async def test_pending_source_error_not_zero():
    class Broken:
        async def list(self):
            raise TimeoutError("secret internal detail")

    result = await pending(Broken(), NOW)
    assert result.state == "ERROR"
    assert "secret internal detail" not in result.message


@pytest.mark.asyncio
async def test_degraded_partial_failure_keeps_readable_items():
    run = SimpleNamespace(
        task_run_id=uuid4(),
        status="FAILED",
        error_code="LOCAL_FAILURE",
        started_at=NOW,
        finished_at=None,
    )

    class Store:
        async def runs(self):
            return (run,)

    class Monthly:
        async def runs(self, offset=0):
            raise TimeoutError("private")

    result = await degraded(SimpleNamespace(store=Store()), Monthly())
    assert result.state == "ERROR"
    assert len(result.items) == 1
    assert result.items[0].detail_url.startswith("/calendar#daily_task-")
    assert "private" not in result.message


@pytest.mark.asyncio
async def test_degraded_bounded_and_empty():
    class Store:
        def __init__(self, runs):
            self._runs = runs

        async def runs(self):
            return self._runs

    runs = tuple(
        SimpleNamespace(
            task_run_id=uuid4(),
            status="FAILED",
            error_code=None,
            started_at=NOW + timedelta(seconds=i),
            finished_at=None,
        )
        for i in range(LIMIT + 1)
    )
    result = await degraded(SimpleNamespace(store=Store(runs)), None)
    assert result.state == "ERROR"  # missing monthly source must not look successful
    assert len(result.items) == LIMIT
    assert result.limited
    empty = await degraded(SimpleNamespace(store=Store(())), None)
    assert empty.state == "ERROR"  # partial availability, not fabricated global zero


@pytest.mark.asyncio
async def test_successful_task_does_not_hide_degraded_report():
    report_id = uuid4()

    class Store:
        async def runs(self):
            return ()

        async def reports(self):
            return (SimpleNamespace(report_id=report_id, phase="DEGRADED", recorded_at=NOW),)

    class Monthly:
        async def runs(self):
            return ()

    result = await degraded(SimpleNamespace(store=Store()), Monthly())
    assert result.state == "AVAILABLE"
    assert result.items[0].source == "DAILY_REPORT"
    assert result.items[0].detail_url == f"/calendar#daily_report-{report_id}"


@pytest.mark.asyncio
async def test_full_scan_window_discloses_uncounted_records():
    class CenterWindow:
        async def list(self):
            return tuple(SimpleNamespace(state="REJECTED") for _ in range(100))

    result = await pending(CenterWindow(), NOW)
    assert result.state == "EMPTY" and result.limited
    assert "窗口外" in result.message


@pytest.mark.asyncio
async def test_stalled_daily_source_preserves_monthly_records():
    class Store:
        async def runs(self):
            await asyncio.sleep(10)
            return ()

        async def reports(self):
            return ()

    class Monthly:
        async def runs(self):
            return (
                SimpleNamespace(
                    task_run_id=uuid4(),
                    status="FAILED",
                    error_code="LOCAL_FAILURE",
                    started_at=NOW,
                    finished_at=None,
                ),
            )

    result = await degraded(SimpleNamespace(store=Store()), Monthly())
    assert result.state == "ERROR"
    assert len(result.items) == 1 and result.items[0].source == "MONTHLY_TASK"
