from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient

from investment_os.api.app import create_app
from investment_os.infrastructure.onboarding import OnboardingStateRead


class StubOnboardingStore:
    def __init__(self) -> None:
        self.state = OnboardingStateRead(status="NOT_STARTED", started_at=None)

    async def get(self) -> OnboardingStateRead:
        return self.state

    async def start(self) -> OnboardingStateRead:
        self.state = OnboardingStateRead(
            status="IN_PROGRESS", started_at=datetime(2026, 9, 21, tzinfo=UTC)
        )
        return self.state


async def test_onboarding_api_is_persistent_boundary_and_exposes_no_secrets() -> None:
    store = StubOnboardingStore()
    app = create_app(onboarding_store=store)  # type: ignore[arg-type]

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
        "CONFIGURATION_REQUIRED",
        "NOT_IMPLEMENTED",
    }
    assert "secret" not in str(capabilities.json()).lower()
