"""Explicit daily authorization commands; no implicit enable or provider calls."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from investment_os.application.daily_runtime import (
    DailyConfiguration,
    DailyError,
    DailyMode,
    DailyPrepared,
    DailyReport,
    DailyReportAudit,
    DailyRuntimeService,
    DailySave,
    DailyTask,
)


def daily_router(service: DailyRuntimeService | None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/runtime/daily", tags=["daily-runtime"])

    def ready() -> DailyRuntimeService:
        if service is None:
            raise HTTPException(
                503,
                detail={
                    "code": "DAILY_UNAVAILABLE",
                    "message": "每日运行时未装配, 未发起任何调用。",
                },
            )
        return service

    def failed(exc: DailyError) -> HTTPException:
        return HTTPException(
            404 if exc.code.endswith("NOT_FOUND") else 409 if "CONFLICT" in exc.code else 422,
            detail={
                "code": exc.code,
                "message": f"授权边界不满足 ({exc.code}); 请刷新核对范围、日历和费用, 未扩大权限。",
            },
        )

    @router.get("", response_model=tuple[DailyConfiguration, ...])
    async def configurations(
        offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=50)
    ) -> tuple[DailyConfiguration, ...]:
        try:
            if offset == 0 and limit == 50:
                return await ready().store.configurations()
            return await ready().store.configurations(offset=offset, limit=limit)
        except DailyError as exc:
            raise failed(exc) from None

    @router.get("/runs", response_model=tuple[DailyTask, ...])
    async def runs(
        offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)
    ) -> tuple[DailyTask, ...]:
        try:
            if offset == 0 and limit == 100:
                return await ready().store.runs()
            return await ready().store.runs(offset=offset, limit=limit)
        except DailyError as exc:
            raise failed(exc) from None

    @router.get("/reports", response_model=tuple[DailyReport, ...])
    async def reports(
        schedule_id: UUID | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=100),
    ) -> tuple[DailyReport, ...]:
        try:
            if offset == 0 and limit == 100:
                return await ready().store.reports(schedule_id)
            return await ready().store.reports(schedule_id, offset=offset, limit=limit)
        except DailyError as exc:
            raise failed(exc) from None

    @router.get("/history", response_model=tuple[DailyReportAudit, ...])
    async def history(
        offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)
    ) -> tuple[DailyReportAudit, ...]:
        try:
            return await ready().store.report_history(offset=offset, limit=limit)
        except DailyError as exc:
            raise failed(exc) from None

    @router.get("/reports/{report_id}", response_model=DailyReport)
    async def report(report_id: UUID) -> DailyReport:
        try:
            return await ready().store.report(report_id)
        except DailyError as exc:
            raise failed(exc) from None

    @router.get("/runs/{task_id}", response_model=DailyTask)
    async def task(task_id: UUID) -> DailyTask:
        try:
            return await ready().store.task(task_id)
        except DailyError as exc:
            raise failed(exc) from None

    @router.get("/configurations/{schedule_id}", response_model=DailyConfiguration)
    async def configuration(schedule_id: UUID) -> DailyConfiguration:
        try:
            return await ready().store.configuration(schedule_id)
        except DailyError as exc:
            raise failed(exc) from None

    @router.post("/preview", response_model=DailyPrepared)
    async def preview(command: DailySave) -> DailyPrepared:
        try:
            return await ready().setup.prepare(command, datetime.now(UTC))
        except DailyError as exc:
            raise failed(exc) from None

    @router.post("", response_model=DailyConfiguration)
    async def save(command: DailySave) -> DailyConfiguration:
        try:
            return await ready().save(command)
        except DailyError as exc:
            raise failed(exc) from None

    @router.post("/{schedule_id}/mode", response_model=DailyConfiguration)
    async def mode(schedule_id: UUID, command: DailyMode) -> DailyConfiguration:
        try:
            return await ready().store.mode(schedule_id, command)
        except DailyError as exc:
            raise failed(exc) from None

    return router
