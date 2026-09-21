from datetime import UTC, datetime

from investment_os.application.onboarding import OnboardingService, OnboardingState


class RecordingOnboardingPort:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.state = OnboardingState(status="NOT_STARTED", started_at=None)

    async def get(self) -> OnboardingState:
        self.calls.append("get")
        return self.state

    async def start(self) -> OnboardingState:
        self.calls.append("start")
        self.state = OnboardingState(
            status="IN_PROGRESS",
            started_at=datetime(2026, 9, 21, tzinfo=UTC),
        )
        return self.state


async def test_onboarding_service_delegates_to_the_application_port() -> None:
    port = RecordingOnboardingPort()
    service = OnboardingService(port)

    assert (await service.current_state()).status == "NOT_STARTED"
    assert (await service.start()).status == "IN_PROGRESS"
    assert port.calls == ["get", "start"]
