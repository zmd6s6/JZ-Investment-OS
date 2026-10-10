"""Replaceable structured market-data port for PRODUCT-06 valuation inputs.

Bocha Web Search is a research text source only; it must never satisfy this port.
Missing quotes fail closed. Values are Decimal; no LLM estimates are accepted here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from investment_os.domain.values import exact_decimal


@dataclass(frozen=True, slots=True)
class MarketQuote:
    instrument_id: UUID
    reference_price: Decimal
    currency: str
    as_of: datetime
    source: str
    volatility: Decimal = Decimal("0.20")


class MarketDataPort(Protocol):
    async def get_reference_quotes(
        self,
        instrument_ids: tuple[UUID, ...],
        *,
        as_of: datetime,
    ) -> dict[UUID, MarketQuote]: ...


class InMemoryMarketDataAdapter:
    """Development/synthetic adapter; prices must be explicitly provided."""

    def __init__(self, quotes: dict[UUID, MarketQuote] | None = None) -> None:
        self._quotes = dict(quotes or {})

    def put(self, quote: MarketQuote) -> None:
        self._quotes[quote.instrument_id] = quote

    async def get_reference_quotes(
        self,
        instrument_ids: tuple[UUID, ...],
        *,
        as_of: datetime,
    ) -> dict[UUID, MarketQuote]:
        found: dict[UUID, MarketQuote] = {}
        for instrument_id in instrument_ids:
            quote = self._quotes.get(instrument_id)
            if quote is None:
                continue
            if quote.as_of > as_of:
                continue
            found[instrument_id] = quote
        return found


def ensure_price(value: Decimal | str | int, field: str = "price") -> Decimal:
    price = exact_decimal(value)
    if price <= 0:
        raise ValueError(f"{field} must be positive")
    return price


__all__ = [
    "InMemoryMarketDataAdapter",
    "MarketDataPort",
    "MarketQuote",
    "ensure_price",
]
