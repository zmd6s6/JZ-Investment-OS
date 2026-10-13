"""Chained market data source priority, degradation markers, and source attribution."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from investment_os.application.market_data import (
    ChainedMarketDataPort,
    InMemoryMarketDataAdapter,
    MarketQuote,
)


class _EmptySource:
    name = "EMPTY"

    async def get_quotes(self, requests, *, as_of):
        return {}


class _FakeSource:
    def __init__(self, name: str, prices: dict[str, Decimal]):
        self.name = name
        self._prices = prices

    async def get_quotes(self, requests, *, as_of):
        found = {}
        for req in requests:
            price = self._prices.get(req.symbol)
            if price is None:
                continue
            found[req.instrument_id] = MarketQuote(
                instrument_id=req.instrument_id,
                reference_price=price,
                currency="CNY",
                as_of=as_of,
                source=self.name,
            )
        return found


async def test_chain_uses_primary_then_marks_degraded_fallback() -> None:
    now = datetime(2026, 10, 10, tzinfo=UTC)
    a = uuid4()
    b = uuid4()
    instruments = {
        a: ("SSE", "600519", "CNY"),
        b: ("SZSE", "000001", "CNY"),
    }
    chain = ChainedMarketDataPort(
        (
            _FakeSource("PRIMARY", {"600519": Decimal("1500")}),  # type: ignore[arg-type]
            _FakeSource("SECONDARY", {"600519": Decimal("1501"), "000001": Decimal("12")}),  # type: ignore[arg-type]
        )
    )
    quotes = await chain.get_reference_quotes((a, b), as_of=now, instruments=instruments)
    assert quotes[a].source == "PRIMARY"
    assert quotes[a].degraded is False
    assert quotes[a].source_rank == 0
    assert quotes[b].source == "SECONDARY"
    assert quotes[b].degraded is True
    assert quotes[b].source_rank == 1


async def test_chain_falls_back_to_synthetic_when_real_sources_miss() -> None:
    now = datetime(2026, 10, 10, tzinfo=UTC)
    instrument_id = uuid4()
    memory = InMemoryMarketDataAdapter()
    memory.put(
        MarketQuote(
            instrument_id=instrument_id,
            reference_price=Decimal("10"),
            currency="CNY",
            as_of=now,
            source="will-be-overwritten",
        )
    )
    chain = ChainedMarketDataPort((_EmptySource(), memory))  # type: ignore[arg-type]
    quotes = await chain.get_reference_quotes(
        (instrument_id,),
        as_of=now,
        instruments={instrument_id: ("SSE", "600000", "CNY")},
    )
    assert quotes[instrument_id].source == "SYNTHETIC"
    assert quotes[instrument_id].degraded is True
