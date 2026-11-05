"""Explicit monthly local authorization and verified frozen replay, never new research."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException

from investment_os.application.daily_runtime import DailyMode, DailyTask
from investment_os.application.monthly_review import (
    MonthlyConfiguration,
    MonthlyConfirm,
    MonthlyError,
    MonthlyPrepared,
    MonthlyReport,
    MonthlyReportHistory,
    MonthlyReviewPort,
    MonthlySave,
)


def monthly_router(service: MonthlyReviewPort | None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/runtime/monthly", tags=["monthly-review"])

    def ready() -> MonthlyReviewPort:
        if service is None:
            raise HTTPException(
                503, detail={"code": "MONTHLY_UNAVAILABLE", "message": "月度复核未装配。"}
            )
        return service

    def failed(exc: MonthlyError) -> HTTPException:
        return HTTPException(
            409 if "CONFLICT" in exc.code or "STALE" in exc.code else 422,
            detail={
                "code": exc.code,
                "message": f"月度边界不满足 ({exc.code}); 请刷新核对授权/范围/日历。未扩大权限。",
            },
        )

    @router.get("", response_model=tuple[MonthlyConfiguration, ...])
    async def configurations() -> tuple[MonthlyConfiguration, ...]:
        try:
            return await ready().configurations()
        except MonthlyError as exc:
            raise failed(exc) from None

    @router.post("/preview", response_model=MonthlyPrepared)
    async def preview(command: MonthlySave) -> MonthlyPrepared:
        try:
            return await ready().preview(command, datetime.now(UTC))
        except MonthlyError as exc:
            raise failed(exc) from None

    @router.post("", response_model=MonthlyConfiguration)
    async def save(command: MonthlyConfirm) -> MonthlyConfiguration:
        try:
            return await ready().save(command.command, command.preview_hash)
        except MonthlyError as exc:
            raise failed(exc) from None

    @router.post("/{schedule_id}/mode", response_model=MonthlyConfiguration)
    async def mode(schedule_id: UUID, command: DailyMode) -> MonthlyConfiguration:
        try:
            return await ready().mode(schedule_id, command)
        except MonthlyError as exc:
            raise failed(exc) from None

    @router.get("/reports", response_model=tuple[MonthlyReport, ...])
    async def reports(schedule_id: UUID | None = None) -> tuple[MonthlyReport, ...]:
        try:
            return await ready().reports(schedule_id)
        except MonthlyError as exc:
            raise failed(exc) from None

    @router.get("/reports/{report_id}/replay", response_model=MonthlyReport)
    async def replay(report_id: UUID) -> MonthlyReport:
        try:
            return await ready().replay(report_id)
        except MonthlyError as exc:
            raise failed(exc) from None

    @router.get("/history", response_model=tuple[MonthlyReportHistory, ...])
    async def history() -> tuple[MonthlyReportHistory, ...]:
        return await ready().history()

    @router.get("/runs", response_model=tuple[DailyTask, ...])
    async def runs() -> tuple[DailyTask, ...]:
        return await ready().runs()

    return router
