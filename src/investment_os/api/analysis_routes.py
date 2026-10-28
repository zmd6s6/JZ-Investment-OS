"""Persistent queued analysis; requests authorize research only, never an order."""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from investment_os.application.analysis_choices import AnalysisChoices, AnalysisChoicesService
from investment_os.application.analysis_configuration import AnalysisStartService
from investment_os.application.analysis_runs import (
    AnalysisRunView,
    AnalysisStart,
    AnalysisStorePort,
)
from investment_os.application.errors import ApplicationError


def analysis_router(
    start: AnalysisStartService | None,
    store: AnalysisStorePort | None,
    choices: AnalysisChoicesService | None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])

    def available() -> AnalysisStorePort:
        if start is None or store is None or choices is None:
            raise HTTPException(
                503,
                detail={
                    "code": "ANALYSIS_UNAVAILABLE",
                    "message": "分析服务未装配, 请核对 API 与 Worker 部署版本。",
                },
            )
        return store

    def failure(exc: Exception) -> HTTPException:
        code = exc.code.value if isinstance(exc, ApplicationError) else str(exc)
        # No raw provider text or arbitrary exception is reflected to the browser.
        safe = code if code.startswith("ANALYSIS_") else "ANALYSIS_INPUT_UNAVAILABLE"
        return HTTPException(
            409 if "CONFLICT" in safe else 422,
            detail={
                "code": safe,
                "message": "分析输入未就绪或已变化, 请刷新配置并核对组合、标的、模型凭据和预算。",
            },
        )

    @router.get("/choices", response_model=AnalysisChoices)
    async def get_choices(instrument_id: UUID) -> AnalysisChoices:
        available()
        assert choices is not None
        return await choices.get(instrument_id)

    @router.post("/runs", response_model=AnalysisRunView, status_code=202)
    async def create(command: AnalysisStart) -> AnalysisRunView:
        available()
        assert start is not None
        try:
            return await start.start(command)
        except (ValueError, LookupError, ApplicationError) as exc:
            raise failure(exc) from None

    @router.get("/runs", response_model=tuple[AnalysisRunView, ...])
    async def list_runs(portfolio_id: UUID | None = None) -> tuple[AnalysisRunView, ...]:
        return await available().list_runs(portfolio_id=portfolio_id)

    @router.get("/runs/{run_id}", response_model=AnalysisRunView)
    async def get(run_id: UUID) -> AnalysisRunView:
        try:
            return await available().get(run_id)
        except LookupError:
            raise HTTPException(404, detail={"code": "ANALYSIS_NOT_FOUND"}) from None

    @router.post("/runs/{run_id}/cancel", response_model=AnalysisRunView)
    async def cancel(run_id: UUID) -> AnalysisRunView:
        try:
            return await available().cancel(run_id)
        except LookupError:
            raise HTTPException(404, detail={"code": "ANALYSIS_NOT_FOUND"}) from None

    return router
