"""Tushare market data adapter for CNY reference prices (httpx, no new dependency)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx

from investment_os.application.market_data import (
    MarketQuote,
    QuoteRequest,
    ensure_price,
    tushare_symbol,
)

TUSHARE_PROVIDER_TYPE = "TUSHARE_MARKET"
TUSHARE_URL = "https://api.tushare.pro"


class TushareMarketDataAdapter:
    """Owner-configured Tushare daily quotes. Missing token/quote fails closed."""

    name = "TUSHARE"

    def __init__(
        self,
        *,
        token: str,
        client: httpx.AsyncClient | None = None,
        profile_id: UUID | None = None,
    ) -> None:
        self._token = token.strip()
        self._client = client or httpx.AsyncClient(timeout=15.0)
        self._owns_client = client is None
        self._profile_id = profile_id

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_quotes(
        self,
        requests: tuple[QuoteRequest, ...],
        *,
        as_of: datetime,
    ) -> dict[UUID, MarketQuote]:
        if not self._token:
            return {}
        if not requests:
            return {}
        ts_codes = [tushare_symbol(req.market, req.symbol) for req in requests]
        # Tushare daily supports up to ~2000 codes; batch conservatively.
        payload = {
            "api_name": "daily",
            "token": self._token,
            "params": {"trade_date": as_of.strftime("%Y%m%d")},
            "fields": "ts_code,trade_date,close",
        }
        try:
            response = await self._client.post(TUSHARE_URL, json=payload)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError):
            return {}
        if not isinstance(body, dict) or body.get("code") != 0:
            return {}
        # Official Tushare envelope: {code, msg, data: {fields, items}}
        data = body.get("data")
        if not isinstance(data, dict):
            return {}
        items = data.get("items") or []
        fields = data.get("fields") or []
        if not isinstance(items, list) or not isinstance(fields, list):
            return {}
        try:
            code_idx = fields.index("ts_code")
            date_idx = fields.index("trade_date")
            close_idx = fields.index("close")
        except ValueError:
            return {}
        by_ts: dict[str, Any] = {}
        for row in items:
            if not isinstance(row, list) or len(row) <= max(code_idx, close_idx):
                continue
            by_ts[str(row[code_idx])] = row
        found: dict[UUID, MarketQuote] = {}
        for req, ts_code in zip(requests, ts_codes, strict=True):
            row = by_ts.get(ts_code)
            if row is None:
                continue
            try:
                price = ensure_price(row[close_idx])
            except ValueError:
                continue
            trade_date = str(row[date_idx])
            quote_as_of = datetime.strptime(trade_date, "%Y%m%d")
            if quote_as_of.tzinfo is None:
                from datetime import UTC

                quote_as_of = quote_as_of.replace(tzinfo=UTC)
            if quote_as_of > as_of:
                continue
            found[req.instrument_id] = MarketQuote(
                instrument_id=req.instrument_id,
                reference_price=price,
                currency=req.expected_currency or "CNY",
                as_of=quote_as_of,
                source=self.name,
                source_rank=0,
                degraded=False,
                volatility=Decimal("0.20"),
                provider_detail=f"TUSHARE daily {ts_code} {trade_date}",
            )
        return found
