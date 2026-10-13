"""Multi-source structured market-data with explicit source markers and degradation.

Bocha Web Search is a research text source only; it must never satisfy this port.
Missing quotes fail closed. Values are Decimal; no LLM estimates are accepted.

Chain semantics:
- Sources are tried in configured priority order.
- A non-primary source that supplies a quote is marked ``degraded=True``.
- The actual source name is always recorded on the quote (no silent attribution).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from investment_os.domain.values import exact_decimal


@dataclass(frozen=True, slots=True)
class QuoteRequest:
    instrument_id: UUID
    market: str
    symbol: str
    expected_currency: str = "CNY"


@dataclass(frozen=True, slots=True)
class MarketQuote:
    instrument_id: UUID
    reference_price: Decimal
    currency: str
    as_of: datetime
    source: str
    source_rank: int = 0
    degraded: bool = False
    volatility: Decimal = Decimal("0.20")
    provider_detail: str = ""


class MarketDataSourcePort(Protocol):
    """One configured quote provider (e.g. TUSHARE, SYNTHETIC)."""

    name: str

    async def get_quotes(
        self,
        requests: tuple[QuoteRequest, ...],
        *,
        as_of: datetime,
    ) -> dict[UUID, MarketQuote]: ...


class MarketDataPort(Protocol):
    async def get_reference_quotes(
        self,
        instrument_ids: tuple[UUID, ...],
        *,
        as_of: datetime,
        instruments: dict[UUID, tuple[str, str, str]] | None = None,
    ) -> dict[UUID, MarketQuote]: ...


class InMemoryMarketDataAdapter:
    """Development/synthetic adapter; prices must be explicitly provided."""

    name = "SYNTHETIC"

    def __init__(self, quotes: dict[UUID, MarketQuote] | None = None) -> None:
        self._quotes = dict(quotes or {})

    def put(self, quote: MarketQuote) -> None:
        self._quotes[quote.instrument_id] = replace(
            quote, source=self.name, source_rank=0, degraded=False
        )

    async def get_quotes(
        self,
        requests: tuple[QuoteRequest, ...],
        *,
        as_of: datetime,
    ) -> dict[UUID, MarketQuote]:
        found: dict[UUID, MarketQuote] = {}
        for req in requests:
            quote = self._quotes.get(req.instrument_id)
            if quote is None or quote.as_of > as_of:
                continue
            found[req.instrument_id] = replace(
                quote, source=self.name, source_rank=0, degraded=False
            )
        return found

    async def get_reference_quotes(
        self,
        instrument_ids: tuple[UUID, ...],
        *,
        as_of: datetime,
        instruments: dict[UUID, tuple[str, str, str]] | None = None,
    ) -> dict[UUID, MarketQuote]:
        requests = tuple(
            QuoteRequest(instrument_id=i, market="", symbol="") for i in instrument_ids
        )
        return await self.get_quotes(requests, as_of=as_of)


class ChainedMarketDataPort:
    """Try sources in order; mark non-primary hits as degraded and name the source."""

    def __init__(
        self,
        sources: tuple[MarketDataSourcePort, ...],
        *,
        volatility_default: Decimal = Decimal("0.20"),
    ) -> None:
        if not sources:
            raise ValueError("at least one market data source is required")
        self._sources = sources
        self._volatility_default = volatility_default

    @property
    def source_names(self) -> tuple[str, ...]:
        return tuple(source.name for source in self._sources)

    async def get_reference_quotes(
        self,
        instrument_ids: tuple[UUID, ...],
        *,
        as_of: datetime,
        instruments: dict[UUID, tuple[str, str, str]] | None = None,
    ) -> dict[UUID, MarketQuote]:
        """``instruments`` maps id -> (market, symbol, expected_currency)."""

        mapping = instruments or {}
        quote_requests = tuple(
            QuoteRequest(
                instrument_id=i,
                market=mapping.get(i, ("", "", "CNY"))[0],
                symbol=mapping.get(i, ("", "", "CNY"))[1],
                expected_currency=mapping.get(i, ("", "", "CNY"))[2] or "CNY",
            )
            for i in instrument_ids
        )
        pending = {req.instrument_id: req for req in quote_requests}
        found: dict[UUID, MarketQuote] = {}
        for rank, source in enumerate(self._sources):
            if not pending:
                break
            batch = tuple(pending.values())
            quotes = await source.get_quotes(batch, as_of=as_of)
            for instrument_id, quote in quotes.items():
                found[instrument_id] = replace(
                    quote,
                    source=source.name,
                    source_rank=rank,
                    degraded=rank > 0,
                    volatility=self._volatility_default,
                )
                pending.pop(instrument_id, None)
        return found


def ensure_price(value: Decimal | str | int, field: str = "price") -> Decimal:
    price = exact_decimal(value)
    if price <= 0:
        raise ValueError(f"{field} must be positive")
    return price


def tushare_symbol(market: str, symbol: str) -> str:
    """Map internal market codes to Tushare daily bar symbols."""
    market_u = market.strip().upper()
    symbol_u = symbol.strip().upper()
    if market_u in {"SSE", "SH", "SHANGHAI"}:
        return f"{symbol_u}.SH"
    if market_u in {"SZSE", "SZ", "SHENZHEN"}:
        return f"{symbol_u}.SZ"
    if market_u in {"HKEX", "HK"}:
        return f"{symbol_u}.HK"
    return f"{symbol_u}.{market_u}"


__all__ = [
    "ChainedMarketDataPort",
    "InMemoryMarketDataAdapter",
    "MarketDataPort",
    "MarketDataSourcePort",
    "MarketQuote",
    "QuoteRequest",
    "ensure_price",
    "tushare_symbol",
]
