"""Tushare market data adapter for CNY reference prices (httpx, no new dependency)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx

from investment_os.application.market_data import (
    InMemoryMarketDataAdapter,
    MarketQuote,
    QuoteRequest,
    ensure_price,
    tushare_symbol,
)

TUSHARE_PROVIDER_TYPE = "TUSHARE_MARKET"
TUSHARE_URL = "https://api.tushare.pro"


class RefreshableTushareChain:
    """Rebuild Tushare sources from current profiles on every quote request.

    Disable/credential rotation take effect on the next call. Synthetic remains last.
    """

    name = "TUSHARE_CHAIN"

    def __init__(
        self,
        *,
        list_profiles: Any,
        get_credential: Any,
        volatility_default: Decimal = Decimal("0.20"),
    ) -> None:
        from investment_os.application.market_data import ChainedMarketDataPort

        self._list_profiles = list_profiles
        self._get_credential = get_credential
        self._chain = ChainedMarketDataPort(
            (InMemoryMarketDataAdapter(),), volatility_default=volatility_default
        )

    async def _refresh_sources(self) -> None:
        from investment_os.application.market_data import (
            InMemoryMarketDataAdapter,
            MarketDataSourcePort,
        )

        try:
            profiles = await self._list_profiles()
        except Exception:
            self._chain._sources = (InMemoryMarketDataAdapter(),)
            return
        extra: list[MarketDataSourcePort] = []
        for profile in sorted(profiles, key=lambda item: item.name):
            if not profile.enabled or profile.provider_type != TUSHARE_PROVIDER_TYPE:
                continue
            if profile.credential_ref is None:
                continue
            try:
                credential = await self._get_credential(profile.credential_ref)
            except Exception:
                credential = None
            if not credential:
                continue
            extra.append(
                TushareMarketDataAdapter(token=credential, profile_id=getattr(profile, "id", None))
            )
        self._chain._sources = (*extra, InMemoryMarketDataAdapter())

    async def get_reference_quotes(
        self,
        instrument_ids: tuple[UUID, ...],
        *,
        as_of: datetime,
        instruments: dict[UUID, tuple[str, str, str]] | None = None,
    ) -> dict[UUID, MarketQuote]:
        await self._refresh_sources()
        return await self._chain.get_reference_quotes(
            instrument_ids, as_of=as_of, instruments=instruments
        )


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
        payload = {
            "api_name": "daily",
            "token": self._token,
            "params": {"trade_date": as_of.strftime("%Y%m%d")},
            "fields": "ts_code,trade_date,close",
        }
        try:
            response = await self._client.post(TUSHARE_URL, json=payload)
            response.raise_for_status()
            # Parse numbers as Decimal so JSON numeric close prices never become float.
            raw_text = getattr(response, "text", None)
            if isinstance(raw_text, str) and raw_text:
                body = json.loads(raw_text, parse_float=Decimal, parse_int=Decimal)
            else:
                body = json.loads(
                    json.dumps(response.json()),
                    parse_float=Decimal,
                    parse_int=Decimal,
                )
        except (httpx.HTTPError, ValueError, TypeError):
            return {}
        if not isinstance(body, dict) or body.get("code") != 0:
            return {}
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
                close_value = row[close_idx]
                if isinstance(close_value, Decimal):
                    price = ensure_price(close_value)
                else:
                    price = ensure_price(Decimal(str(close_value)))
            except ValueError:
                continue
            trade_date = str(row[date_idx])
            quote_as_of = datetime.strptime(trade_date, "%Y%m%d")
            if quote_as_of.tzinfo is None:
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
