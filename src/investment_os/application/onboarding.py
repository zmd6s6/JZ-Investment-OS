"""Application boundary for the non-sensitive first-run onboarding flow."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

OnboardingStatus = Literal["NOT_STARTED", "IN_PROGRESS"]


@dataclass(frozen=True, slots=True)
class OnboardingState:
    """The only product setup state supported before PRODUCT-02."""

    status: OnboardingStatus
    started_at: datetime | None


class OnboardingStatePort(Protocol):
    """Persist and retrieve non-sensitive onboarding progress."""

    async def get(self) -> OnboardingState: ...

    async def start(self) -> OnboardingState: ...


class OnboardingService:
    """Use case that keeps HTTP transport independent of a persistence adapter."""

    def __init__(self, state_port: OnboardingStatePort) -> None:
        self._state_port = state_port

    async def current_state(self) -> OnboardingState:
        return await self._state_port.get()

    async def start(self) -> OnboardingState:
        return await self._state_port.start()
