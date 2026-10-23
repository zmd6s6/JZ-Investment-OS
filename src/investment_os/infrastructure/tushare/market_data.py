"""Tushare market data adapter for CNY reference prices (httpx, no new dependency)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx

from investment_os.application.market_data import (
    InMemoryMarketDataAdapter,
    MarketDataSourceFailure,
    MarketQuote,
    QuoteRequest,
    ensure_price,
    tushare_symbol,
)
from investment_os.application.market_features import DailyMarketBar
from investment_os.domain.errors import DomainError
from investment_os.domain.values import exact_decimal

TUSHARE_PROVIDER_TYPE = "TUSHARE_MARKET"
TUSHARE_URL = "https://api.tushare.pro"


def _daily_bar(
    fields: list[str], row: list[Any], request: QuoteRequest, as_of: datetime, price: Decimal
) -> DailyMarketBar | None:
    optional = ("open", "high", "low", "pre_close", "vol", "amount")
    if not any(name in fields for name in optional):
        return None

    def number(name: str) -> Decimal | None:
        if name not in fields:
            return None
        index = fields.index(name)
        if index >= len(row):
            raise ValueError("daily row incomplete")
        return exact_decimal(row[index]) if row[index] is not None else None

    with localcontext(Context(prec=128, rounding=ROUND_HALF_EVEN)):
        volume, turnover = number("vol"), number("amount")
        return DailyMarketBar(
            instrument_id=request.instrument_id,
            as_of=as_of,
            close=price,
            open=number("open"),
            high=number("high"),
            low=number("low"),
            previous_close=number("pre_close"),
            volume_shares=volume * Decimal("100") if volume is not None else None,
            turnover=turnover * Decimal("1000") if turnover is not None else None,
            previous_close_basis="EX_RIGHTS",
        )


class TushareConnectionTester:
    """Explicit Tushare connectivity check for settings UI (no secret persisted)."""

    name = "TUSHARE_MARKET"

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=10.0)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def test(self, *, credential: str) -> tuple[bool, str, int | None]:
        """Return (ok, detail, latency_ms). Uses a cheap official API call."""
        payload = {
            "api_name": "trade_cal",
            "token": credential,
            "params": {"exchange": "SSE", "start_date": "20240101", "end_date": "20240102"},
            "fields": "exchange,cal_date",
        }
        try:
            response = await self._client.post(TUSHARE_URL, json=payload)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return False, f"Tushare 网络或解析失败: {exc}", None
        if not isinstance(body, dict) or body.get("code") != 0:
            msg = body.get("msg") if isinstance(body, dict) else "invalid response"
            return False, f"Tushare 返回错误: {msg}", None
        data = body.get("data")
        items = data.get("items") if isinstance(data, dict) else None
        if not items:
            return False, "Tushare 连接成功但 trade_cal 无数据", None
        return True, "Tushare trade_cal 连接成功", None


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
    ) -> None:
        from investment_os.application.market_data import ChainedMarketDataPort

        self._list_profiles = list_profiles
        self._get_credential = get_credential
        self._chain = ChainedMarketDataPort((InMemoryMarketDataAdapter(),))

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
        if as_of.tzinfo is None:
            raise MarketDataSourceFailure("market request time must be aware")
        if not self._token:
            return {}
        requests = tuple(
            req
            for req in requests
            if req.market in {"SSE", "SZSE"} and req.expected_currency == "CNY"
        )
        if not requests:
            return {}
        ts_codes = [tushare_symbol(req.market, req.symbol) for req in requests]
        payload = {
            "api_name": "daily",
            "token": self._token,
            "params": {
                "trade_date": as_of.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
            },
            "fields": "ts_code,trade_date,close,open,high,low,pre_close,vol,amount",
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
        except (httpx.HTTPError, ValueError, TypeError) as error:
            raise MarketDataSourceFailure("market provider request failed") from error
        if not isinstance(body, dict) or body.get("code") != 0:
            raise MarketDataSourceFailure("market provider rejected request")
        data = body.get("data")
        if not isinstance(data, dict):
            raise MarketDataSourceFailure("market provider schema invalid")
        items = data.get("items")
        fields = data.get("fields")
        if not isinstance(items, list) or not isinstance(fields, list):
            raise MarketDataSourceFailure("market provider schema invalid")
        if not all(isinstance(field, str) for field in fields) or len(fields) != len(set(fields)):
            raise MarketDataSourceFailure("market provider fields ambiguous")
        try:
            code_idx = fields.index("ts_code")
            date_idx = fields.index("trade_date")
            close_idx = fields.index("close")
        except ValueError as error:
            raise MarketDataSourceFailure("market provider schema invalid") from error
        by_ts: dict[str, Any] = {}
        for row in items:
            if not isinstance(row, list) or len(row) <= max(code_idx, close_idx, date_idx):
                raise MarketDataSourceFailure("market provider row invalid")
            if str(row[code_idx]) in by_ts:
                raise MarketDataSourceFailure("market provider duplicate quote")
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
            except (ValueError, TypeError, InvalidOperation, DomainError) as error:
                raise MarketDataSourceFailure("market provider price invalid") from error
            trade_date = str(row[date_idx])
            try:
                # A daily close is not available at midnight. SSE/SZSE regular close is
                # 15:00 Asia/Shanghai; no prior-day or synthetic price is substituted.
                quote_as_of = (
                    datetime.strptime(trade_date, "%Y%m%d")
                    .replace(hour=15, tzinfo=ZoneInfo("Asia/Shanghai"))
                    .astimezone(UTC)
                )
            except ValueError as error:
                raise MarketDataSourceFailure("market provider date invalid") from error
            if quote_as_of > as_of:
                continue
            try:
                daily_bar = _daily_bar(fields, row, req, quote_as_of, price)
            except (ValueError, TypeError, InvalidOperation, DomainError) as error:
                raise MarketDataSourceFailure("market provider daily fields invalid") from error
            found[req.instrument_id] = MarketQuote(
                instrument_id=req.instrument_id,
                reference_price=price,
                currency=req.expected_currency or "CNY",
                as_of=quote_as_of,
                source=self.name,
                source_rank=0,
                degraded=False,
                provider_detail=f"TUSHARE daily {ts_code} {trade_date}",
                daily_bar=daily_bar,
            )
        return found
