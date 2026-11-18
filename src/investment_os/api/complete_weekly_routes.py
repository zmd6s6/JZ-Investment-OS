"""Explicit, paused-by-default weekly local screening configuration and history."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from investment_os.application.complete_weekly import (
    CompleteWeeklyConfiguration,
    CompleteWeeklyOverview,
    CompleteWeeklySave,
    CompleteWeeklyService,
)
from investment_os.application.opportunities import OpportunityError
from investment_os.application.opportunity_schedule import WeeklyMode
from investment_os.application.universe_snapshots import UniverseError
from investment_os.application.weekly_task_history import WeeklyTaskDetail, WeeklyTaskPage


def complete_weekly_router(service: CompleteWeeklyService | None) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/opportunities/complete-weekly", tags=["opportunities-weekly"]
    )

    def ready() -> CompleteWeeklyService:
        if service is None:
            raise HTTPException(
                503,
                detail={"code": "WEEKLY_UNAVAILABLE", "message": "本地周筛选未装配, 未运行任务。"},
            )
        return service

    def failed(exc: OpportunityError | UniverseError) -> HTTPException:
        return HTTPException(
            409 if "CONFLICT" in exc.code else 422,
            detail={
                "code": exc.code,
                "message": (
                    "配置或日历已变化, 请刷新核对版本、市场、范围及完整自然周。没有启用外部调用。"
                ),
            },
        )

    @router.get("", response_model=CompleteWeeklyOverview)
    async def overview() -> CompleteWeeklyOverview:
        try:
            return await ready().overview()
        except (OpportunityError, UniverseError) as exc:
            raise failed(exc) from None

    @router.get("/tasks", response_model=WeeklyTaskPage)
    async def tasks(cursor: str | None = Query(None, max_length=1024)) -> WeeklyTaskPage:
        try:
            return await ready().tasks(cursor)
        except OpportunityError as exc:
            raise HTTPException(
                422,
                detail={"code": exc.code, "message": "周任务分页无效。请刷新后重试。"},
            ) from None

    @router.get("/tasks/{task_run_id}", response_model=WeeklyTaskDetail)
    async def task(task_run_id: str) -> WeeklyTaskDetail:
        try:
            identifier = UUID(task_run_id)
        except ValueError:
            raise HTTPException(
                422,
                detail={
                    "code": "WEEKLY_TASK_ID_INVALID",
                    "message": "周任务ID格式无效。请核对原链接。",
                },
            ) from None
        try:
            return await ready().task(identifier)
        except OpportunityError as exc:
            raise HTTPException(
                404,
                detail={"code": exc.code, "message": "未找到该协议下的周任务。请核对协议和ID。"},
            ) from None

    @router.post("", response_model=CompleteWeeklyConfiguration)
    async def save(command: CompleteWeeklySave) -> CompleteWeeklyConfiguration:
        try:
            return await ready().save(command)
        except (OpportunityError, UniverseError) as exc:
            raise failed(exc) from None

    @router.post("/{schedule_id}/mode", response_model=CompleteWeeklyConfiguration)
    async def mode(schedule_id: UUID, command: WeeklyMode) -> CompleteWeeklyConfiguration:
        try:
            return await ready().mode(schedule_id, command)
        except (OpportunityError, UniverseError) as exc:
            raise failed(exc) from None

    return router
