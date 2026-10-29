"""Explicit, paused-by-default weekly local screening configuration and history."""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from investment_os.application.opportunities import OpportunityError
from investment_os.application.opportunity_schedule import (
    WeeklyConfiguration,
    WeeklyMode,
    WeeklyOverview,
    WeeklySave,
    WeeklyService,
)


def weekly_router(service: WeeklyService | None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/opportunities/weekly", tags=["opportunities-weekly"])

    def ready() -> WeeklyService:
        if service is None:
            raise HTTPException(
                503,
                detail={"code": "WEEKLY_UNAVAILABLE", "message": "本地周筛选未装配, 未运行任务。"},
            )
        return service

    def failed(exc: OpportunityError) -> HTTPException:
        return HTTPException(
            409 if "CONFLICT" in exc.code else 422,
            detail={
                "code": exc.code,
                "message": (
                    "配置或日历已变化, 请刷新核对版本、市场、范围及完整自然周。没有启用外部调用。"
                ),
            },
        )

    @router.get("", response_model=WeeklyOverview)
    async def overview() -> WeeklyOverview:
        try:
            return await ready().overview()
        except OpportunityError as exc:
            raise failed(exc) from None

    @router.post("", response_model=WeeklyConfiguration)
    async def save(command: WeeklySave) -> WeeklyConfiguration:
        try:
            return await ready().save(command)
        except OpportunityError as exc:
            raise failed(exc) from None

    @router.post("/{schedule_id}/mode", response_model=WeeklyConfiguration)
    async def mode(schedule_id: UUID, command: WeeklyMode) -> WeeklyConfiguration:
        try:
            return await ready().mode(schedule_id, command)
        except OpportunityError as exc:
            raise failed(exc) from None

    return router
