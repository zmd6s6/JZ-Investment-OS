"""Read-only reference valuation; no sizing/approval/order endpoint."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from investment_os.application.errors import ApplicationError
from investment_os.application.portfolio_valuation import (
    PortfolioValuationService,
    ValuationContext,
)
from investment_os.domain.errors import DomainError


def valuation_router(service: PortfolioValuationService | None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/valuation", tags=["valuation"])

    @router.get("/portfolios/{portfolio_id}", response_model=ValuationContext)
    async def context(
        portfolio_id: UUID,
        source: str = Query(min_length=1, max_length=255),
        source_name: str = Query(min_length=1, max_length=255),
    ) -> ValuationContext:
        if service is None:
            raise HTTPException(status_code=503, detail={"code": "VALUATION_UNAVAILABLE"})
        try:
            return await service.get_context(portfolio_id, source=source, source_name=source_name)
        except (ValueError, DomainError):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "VALUATION_INPUT_OR_SOURCE_INVALID",
                    "message": "估值输入、来源或组合无效; 未生成完整估值, 请核对组合与人工行情。",
                },
            ) from None
        except ApplicationError:
            raise HTTPException(
                status_code=404, detail={"code": "VALUATION_PORTFOLIO_NOT_FOUND"}
            ) from None

    return router
