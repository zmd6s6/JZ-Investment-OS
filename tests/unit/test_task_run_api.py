from datetime import UTC, datetime
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from investment_os.api.app import create_app
from investment_os.infrastructure.scheduler import TaskRunRead


class StubTaskRunReader:
    async def list_recent(self, *, limit: int) -> tuple[TaskRunRead, ...]:
        assert limit == 3
        return (
            TaskRunRead(
                id=uuid4(),
                task_name="daily",
                scheduled_for=datetime(2026, 9, 20, 20, 0, tzinfo=UTC),
                status="FAILED",
                attempt=2,
                idempotency_key="daily:2026-09-20T20:00:00+00:00",
                started_at=datetime(2026, 9, 20, 20, 0, tzinfo=UTC),
                finished_at=datetime(2026, 9, 20, 20, 1, tzinfo=UTC),
                error={"code": "JOB_HANDLER_FAILED", "type": "TimeoutError"},
            ),
        )


async def test_task_runs_are_read_only_and_expose_sanitized_failure() -> None:
    app = create_app(task_run_reader=StubTaskRunReader())  # type: ignore[arg-type]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/task-runs", params={"limit": 3})

    assert response.status_code == 200
    assert response.json()[0]["status"] == "FAILED"
    assert response.json()[0]["error"] == {"code": "JOB_HANDLER_FAILED", "type": "TimeoutError"}


async def test_task_runs_reject_unbounded_limit() -> None:
    app = create_app(task_run_reader=StubTaskRunReader())  # type: ignore[arg-type]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/task-runs", params={"limit": 101})

    assert response.status_code == 422
