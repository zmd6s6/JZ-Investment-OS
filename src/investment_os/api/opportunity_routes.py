"""Explicit screening API. No schedules or research/model side effects."""

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


class OpportunityCapabilities(MarketDto):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    scope: Literal["LOCAL_EXPLICIT_LIST"] = "LOCAL_EXPLICIT_LIST"
    market_universe: Literal["NOT_PROVIDED"] = "NOT_PROVIDED"
    automatic_research: Literal[False] = False
    deep_research: Literal["NOT_PROVIDED"] = "NOT_PROVIDED"
    hard_candidate_limit: Literal[20] = 20
    financial_basis: Literal["CALENDAR_YEAR_CONSOLIDATED_CNY"] = "CALENDAR_YEAR_CONSOLIDATED_CNY"
    independently_verified: Literal[False] = False
    auto_trade: Literal[False] = False


def opportunity_router(service: OpportunityService | None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/opportunities", tags=["opportunities"])

    def ready() -> OpportunityService:
        if service is None:
            raise HTTPException(503, detail={"code": "OPPORTUNITY_SERVICE_UNAVAILABLE"})
        return service

    def failure(error: OpportunityError | MarketDataError | ApplicationError) -> HTTPException:
        if isinstance(error, ApplicationError):
            return HTTPException(404, detail={"code": error.code.value})
        return HTTPException(
            409 if error.code == "REQUEST_CONTENT_CONFLICT" else 422, detail={"code": error.code}
        )

    @router.get("/capabilities", response_model=OpportunityCapabilities)
    async def capabilities() -> OpportunityCapabilities:
        return OpportunityCapabilities(status="AVAILABLE" if service else "UNAVAILABLE")

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
