"""Typed local calendar UI boundary; validation errors never echo uploaded content."""

from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse

from investment_os.application.calendar_product import (
    CalendarConfigurationView,
    CalendarImportCommand,
    CalendarInput,
    CalendarModeCommand,
    CalendarOverview,
    CalendarPreview,
    CalendarProductError,
    CalendarProductService,
    preview_calendar,
)
from investment_os.application.schedule import MarketVenue


class CalendarRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def safe(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError:
                return JSONResponse(
                    status_code=422,
                    content={
                        "detail": {
                            "code": "CALENDAR_REQUEST_INVALID",
                            "message": "日历请求字段无效。请核对市场、来源、确认勾选和CSV长度; "
                            "未保存任何内容。",
                        }
                    },
                )

        return safe


async def _call[T](operation: Awaitable[T]) -> T:
    try:
        return await operation
    except CalendarProductError as exc:
        raise HTTPException(
            status_code=409 if exc.conflict else 422,
            detail={"code": exc.code, "message": exc.message},
        ) from None
    except Exception:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "CALENDAR_SERVICE_UNAVAILABLE",
                "message": "日历服务暂不可用。若刚提交保存, 结果尚未确认; "
                "输入已保留, 请使用同一内容与请求标识重试核对。",
            },
        ) from None


def create_calendar_router(service: CalendarProductService | None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/calendar", tags=["calendar"], route_class=CalendarRoute)

    def available() -> CalendarProductService:
        if service is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "CALENDAR_SERVICE_UNAVAILABLE",
                    "message": "当前部署未装配日历服务, 请检查应用版本。",
                },
            )
        return service

    @router.get("", response_model=CalendarOverview)
    async def overview() -> CalendarOverview:
        return await _call(available().overview())

    @router.post("/preview", response_model=CalendarPreview)
    async def preview(command: CalendarInput) -> CalendarPreview:
        available()
        try:
            return preview_calendar(command)
        except CalendarProductError as exc:
            raise HTTPException(
                status_code=422, detail={"code": exc.code, "message": exc.message}
            ) from None

    @router.post("/imports", response_model=CalendarConfigurationView)
    async def import_calendar(command: CalendarImportCommand) -> CalendarConfigurationView:
        return await _call(available().import_calendar(command))

    @router.post("/{venue}/mode", response_model=CalendarConfigurationView)
    async def mode(venue: MarketVenue, command: CalendarModeCommand) -> CalendarConfigurationView:
        return await _call(available().set_mode(venue, command))

    return router
