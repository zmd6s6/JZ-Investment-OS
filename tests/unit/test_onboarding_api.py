from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient

from investment_os.api.app import create_app
from investment_os.application.onboarding import OnboardingService, OnboardingState


class StubOnboardingPort:
    def __init__(self) -> None:
        self.state = OnboardingState(status="NOT_STARTED", started_at=None)

    async def get(self) -> OnboardingState:
        return self.state

    async def start(self) -> OnboardingState:
        self.state = OnboardingState(
            status="IN_PROGRESS", started_at=datetime(2026, 9, 21, tzinfo=UTC)
        )
        return self.state


async def test_onboarding_api_is_persistent_boundary_and_exposes_no_secrets() -> None:
    app = create_app(onboarding_service=OnboardingService(StubOnboardingPort()))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        initial = await client.get("/api/v1/onboarding")
        started = await client.post("/api/v1/onboarding/start")
        repeated = await client.post("/api/v1/onboarding/start")
        capabilities = await client.get("/api/v1/product-capabilities")

    assert initial.json()["status"] == "NOT_STARTED"
    assert started.json()["status"] == "IN_PROGRESS"
    assert repeated.json() == started.json()
    assert {item["status"] for item in capabilities.json()} == {
        "AVAILABLE",
        "NOT_IMPLEMENTED",
    }
    assert next(item for item in capabilities.json() if item["key"] == "providers")["status"] == (
        "NOT_IMPLEMENTED"
    )
    assert "secret" not in str(capabilities.json()).lower()


async def test_onboarding_api_fails_closed_when_no_use_case_is_injected() -> None:
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/onboarding")

    assert response.status_code == 503
    assert response.json() == {"detail": "onboarding_unavailable"}
