"""Thin read-only HTTP adapter for the operational inbox."""

from fastapi import APIRouter

from investment_os.application.daily_runtime import DailyRuntimeService
from investment_os.application.decision_center import DecisionCenterPort
from investment_os.application.monthly_review import MonthlyReviewPort
from investment_os.application.operational_inbox import OperationalInbox, OperationalInboxService


def operational_inbox_router(
    center: DecisionCenterPort | None,
    daily: DailyRuntimeService | None,
    monthly: MonthlyReviewPort | None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/operational-inbox", tags=["operational-inbox"])
    service = OperationalInboxService(center, daily, monthly)

    @router.get("", response_model=OperationalInbox)
    async def read_inbox() -> OperationalInbox:
        return await service.read()

    return router
