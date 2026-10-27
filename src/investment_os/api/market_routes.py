"""Typed manual market-data product routes; no provider egress or implicit source selection."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime

from investment_os.application.errors import ApplicationError
from investment_os.application.market_data import (
    ManualQuoteInput,
    ManualQuoteSaved,
    MarketDataCapabilities,
    MarketDataError,
    MarketDataRequest,
    MarketDataService,
    MarketDataSnapshot,
)


def market_router(service: MarketDataService | None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/market-data", tags=["market-data"])

    def ready() -> MarketDataService:
        if service is None:
            raise HTTPException(status_code=503, detail={"code": "MARKET_DATA_UNAVAILABLE"})
        return service

    @router.get("/capabilities", response_model=MarketDataCapabilities)
    async def capabilities() -> MarketDataCapabilities:
        return MarketDataCapabilities(
            status="AVAILABLE" if service else "UNAVAILABLE",
            supported_sources=("MANUAL_MARKET",) if service else (),
        )

    @router.post("/manual-quotes", response_model=ManualQuoteSaved)
    async def save_quote(command: ManualQuoteInput) -> ManualQuoteSaved:
        try:
            return await ready().save_quote(command)
        except MarketDataError as exc:
            raise HTTPException(
                status_code=409 if exc.code == "MARKET_REQUEST_CONFLICT" else 422,
                detail={"code": exc.code},
            ) from None
        except ApplicationError as exc:
            raise HTTPException(status_code=404, detail={"code": exc.code.value}) from None

    @router.get("/reference-quote", response_model=MarketDataSnapshot)
    async def quote(
        instrument_id: UUID,
        source_name: str = Query(min_length=1, max_length=255),
        source: str = Query(default="MANUAL_MARKET", min_length=1, max_length=255),
        as_of: AwareDatetime | None = None,
        base_currency: str = Query(default="CNY", pattern=r"^[A-Z]{3}$"),
        portfolio_id: UUID | None = None,
    ) -> MarketDataSnapshot:
        try:
            request = MarketDataRequest(
                instrument_id=instrument_id,
                source=source,
                source_name=source_name,
                as_of=as_of or datetime.now(UTC),
                base_currency=base_currency,
                portfolio_id=portfolio_id,
            )
            return await ready().get_snapshot(request)
        except MarketDataError as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code}) from None
        except ApplicationError as exc:
            raise HTTPException(status_code=404, detail={"code": exc.code.value}) from None

    return router
