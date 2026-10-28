"""Explicit screening and bounded, individually authorized candidate research."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException

from investment_os.application.errors import ApplicationError
from investment_os.application.market_data import MarketDataError, MarketDto
from investment_os.application.opportunities import (
    FactReceipt,
    FunnelQuery,
    FunnelRun,
    ManualScreenFacts,
    OpportunityError,
    OpportunityService,
)
from investment_os.application.opportunity_research import (
    CandidateResearchStart,
    CandidateResearchView,
    OpportunityResearchService,
)


class OpportunityCapabilities(MarketDto):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    scope: Literal["LOCAL_EXPLICIT_LIST"] = "LOCAL_EXPLICIT_LIST"
    market_universe: Literal["NOT_PROVIDED"] = "NOT_PROVIDED"
    automatic_research: Literal[False] = False
    deep_research: Literal["NOT_PROVIDED", "EXPLICIT_SINGLE_CANDIDATE"] = "NOT_PROVIDED"
    hard_candidate_limit: Literal[20] = 20
    financial_basis: Literal["CALENDAR_YEAR_CONSOLIDATED_CNY"] = "CALENDAR_YEAR_CONSOLIDATED_CNY"
    independently_verified: Literal[False] = False
    auto_trade: Literal[False] = False


def opportunity_router(
    service: OpportunityService | None, research: OpportunityResearchService | None = None
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/opportunities", tags=["opportunities"])

    def ready() -> OpportunityService:
        if service is None:
            raise HTTPException(503, detail={"code": "OPPORTUNITY_SERVICE_UNAVAILABLE"})
        return service

    def failure(error: OpportunityError | MarketDataError | ApplicationError) -> HTTPException:
        if isinstance(error, ApplicationError):
            return HTTPException(404, detail={"code": error.code.value})
        return HTTPException(
            409 if error.code == "REQUEST_CONTENT_CONFLICT" else 422,
            detail={
                "code": error.code,
                "message": {
                    "FUNNEL_RUN_NOT_FOUND": "原筛选运行不存在, 请重新读取历史。",
                    "NOT_A_BOUNDED_CANDIDATE": "该标的没有进入本次有界候选, 不能从此筛选发起研究。",
                    "CANDIDATE_INPUT_MISMATCH": "候选证据或行情来源不一致, 请重新读取原候选。",
                    "CANDIDATE_ANALYSIS_MISMATCH": "研究运行与原请求不一致, 未展示或继续执行。",
                    "CANDIDATE_INTENT_INVALID": "研究关联记录无法核对, 请保留历史并检查部署。",
                    "REQUEST_CONTENT_CONFLICT": "该请求编号已使用, 输入变化后请明确创建新请求。",
                }.get(error.code, error.code),
            },
        )

    @router.get("/capabilities", response_model=OpportunityCapabilities)
    async def capabilities() -> OpportunityCapabilities:
        return OpportunityCapabilities(
            status="AVAILABLE" if service else "UNAVAILABLE",
            deep_research="EXPLICIT_SINGLE_CANDIDATE" if research else "NOT_PROVIDED",
        )

    @router.post("/research", response_model=CandidateResearchView, status_code=202)
    async def start_research(command: CandidateResearchStart) -> CandidateResearchView:
        if research is None:
            raise HTTPException(
                503,
                detail={
                    "code": "CANDIDATE_RESEARCH_UNAVAILABLE",
                    "message": "候选研究服务未装配, 未发起调用。",
                },
            )
        try:
            return await research.start(command)
        except (OpportunityError, MarketDataError, ApplicationError) as error:
            raise failure(error) from None
        except (ValueError, LookupError):
            raise HTTPException(
                422,
                detail={
                    "code": "CANDIDATE_ANALYSIS_INPUT_UNAVAILABLE",
                    "message": (
                        "候选研究输入未就绪或已变化, 请核对组合、已启用模型、凭据和预算后明确重试。"
                    ),
                },
            ) from None

    @router.get("/runs/{run_id}/research", response_model=tuple[CandidateResearchView, ...])
    async def research_history(run_id: UUID) -> tuple[CandidateResearchView, ...]:
        if research is None:
            raise HTTPException(503, detail={"code": "CANDIDATE_RESEARCH_UNAVAILABLE"})
        try:
            return await research.list_for(run_id)
        except OpportunityError as error:
            raise failure(error) from None

    @router.post("/facts", response_model=FactReceipt)
    async def facts(command: ManualScreenFacts) -> FactReceipt:
        try:
            return await ready().save_facts(command)
        except (OpportunityError, MarketDataError, ApplicationError) as error:
            raise failure(error) from None

    @router.post("/runs", response_model=FunnelRun)
    async def run(query: FunnelQuery) -> FunnelRun:
        try:
            return await ready().run(query)
        except (OpportunityError, MarketDataError, ApplicationError) as error:
            raise failure(error) from None

    @router.get("/runs", response_model=tuple[FunnelRun, ...])
    async def runs() -> tuple[FunnelRun, ...]:
        try:
            return await ready().list_runs()
        except (OpportunityError, MarketDataError, ApplicationError) as error:
            raise failure(error) from None

    @router.get("/runs/{run_id}", response_model=FunnelRun)
    async def get_run(run_id: UUID) -> FunnelRun:
        try:
            result = await ready().get_run(run_id)
            if result is None:
                raise HTTPException(404, detail={"code": "FUNNEL_RUN_NOT_FOUND"})
            return result
        except (OpportunityError, MarketDataError, ApplicationError) as error:
            raise failure(error) from None

    return router
