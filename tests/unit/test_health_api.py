import pytest
from httpx import ASGITransport, AsyncClient

from investment_os.api.app import create_app
from investment_os.application.health import HealthCheck


class StubProbe:
    def __init__(self, result: HealthCheck) -> None:
        self._result = result
        self.closed = False

    async def check(self) -> HealthCheck:
        return self._result

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_liveness_exposes_development_safety_state() -> None:
    app = create_app(StubProbe(HealthCheck(ready=True, detail="database_ready")))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "1.0",
        "service": "investment-api",
        "status": "alive",
        "mode": "DEVELOPMENT",
        "live_trading": False,
    }


@pytest.mark.asyncio
async def test_readiness_reports_database_ready() -> None:
    app = create_app(StubProbe(HealthCheck(ready=True, detail="database_ready")))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"] == {"database": "database_ready"}
    assert response.json()["live_trading"] is False


@pytest.mark.asyncio
async def test_readiness_fails_closed_when_database_is_unavailable() -> None:
    app = create_app(StubProbe(HealthCheck(ready=False, detail="database_unavailable")))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"] == {"database": "database_unavailable"}
    assert response.json()["live_trading"] is False


@pytest.mark.asyncio
async def test_application_lifespan_closes_owned_probe() -> None:
    probe = StubProbe(HealthCheck(ready=True, detail="database_ready"))
    app = create_app(probe)

    async with app.router.lifespan_context(app):
        assert probe.closed is False

    assert probe.closed is True
