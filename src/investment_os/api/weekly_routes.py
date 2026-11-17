"""Explicit weekly local authorization and verified frozen replay, never new research."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from investment_os.application.daily_runtime import DailyMode, DailyTask
from investment_os.application.weekly_review import (
    WeeklyConfiguration,
    WeeklyConfirm,
    WeeklyError,
    WeeklyPrepared,
    WeeklyReport,
    WeeklyReportHistory,
    WeeklyReviewPort,
    WeeklySave,
)


def weekly_review_router(service: WeeklyReviewPort | None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/runtime/weekly", tags=["weekly-review"])

    def ready() -> WeeklyReviewPort:
        if service is None:
            raise HTTPException(
                503, detail={"code": "WEEKLY_UNAVAILABLE", "message": "周度复核未装配。"}
            )
        return service

    def failed(exc: WeeklyError) -> HTTPException:
        return HTTPException(
            409 if "CONFLICT" in exc.code or "STALE" in exc.code else 422,
            detail={
                "code": exc.code,
                "message": f"周度边界不满足 ({exc.code}); 请刷新核对授权/范围/日历。未扩大权限。",
            },
        )

    @router.get("", response_model=tuple[WeeklyConfiguration, ...])
    async def configurations(
        offset: int = Query(0, ge=0, le=1000000),
    ) -> tuple[WeeklyConfiguration, ...]:
        try:
            return await ready().configurations(offset)
        except WeeklyError as exc:
            raise failed(exc) from None

    @router.post("/preview", response_model=WeeklyPrepared)
    async def preview(command: WeeklySave) -> WeeklyPrepared:
        try:
            return await ready().preview(command, datetime.now(UTC))
        except WeeklyError as exc:
            raise failed(exc) from None

    @router.post("", response_model=WeeklyConfiguration)
    async def save(command: WeeklyConfirm) -> WeeklyConfiguration:
        try:
            return await ready().save(command.command, command.preview_hash)
        except WeeklyError as exc:
            raise failed(exc) from None

    @router.post("/{schedule_id}/mode", response_model=WeeklyConfiguration)
    async def mode(schedule_id: UUID, command: DailyMode) -> WeeklyConfiguration:
        try:
            return await ready().mode(schedule_id, command)
        except WeeklyError as exc:
            raise failed(exc) from None

    @router.get("/reports", response_model=tuple[WeeklyReport, ...])
    async def reports(
        schedule_id: UUID | None = None, offset: int = Query(0, ge=0, le=1000000)
    ) -> tuple[WeeklyReport, ...]:
        try:
            return await ready().reports(schedule_id, offset)
        except WeeklyError as exc:
            raise failed(exc) from None

    @router.get("/reports/{report_id}/replay", response_model=WeeklyReport)
    async def replay(report_id: UUID) -> WeeklyReport:
        try:
            return await ready().replay(report_id)
        except WeeklyError as exc:
            raise failed(exc) from None

    @router.get("/history", response_model=tuple[WeeklyReportHistory, ...])
    async def history(offset: int = Query(0, ge=0, le=1000000)) -> tuple[WeeklyReportHistory, ...]:
        return await ready().history(offset)

    @router.get("/runs", response_model=tuple[DailyTask, ...])
    async def runs(offset: int = Query(0, ge=0, le=1000000)) -> tuple[DailyTask, ...]:
        return await ready().runs(offset)

    return router
