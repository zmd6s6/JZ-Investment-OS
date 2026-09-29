"""PRODUCT-05 instrument identity and catalog service tests."""

from uuid import uuid4

import pytest

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.instrument_catalog import (
    InstrumentCatalogEntry,
    InstrumentCatalogService,
)
from investment_os.domain.errors import DomainError
from investment_os.domain.instrument import InstrumentIdentity


class InMemoryCatalog:
    def __init__(self) -> None:
        self.entries: dict[tuple[str, str], InstrumentCatalogEntry] = {}

    async def upsert(self, identity: InstrumentIdentity) -> InstrumentCatalogEntry:
        key = identity.natural_key
        existing = self.entries.get(key)
        entry = InstrumentCatalogEntry(
            instrument_id=existing.instrument_id if existing else uuid4(),
            market=identity.market,
            symbol=identity.symbol,
            name=identity.name,
            asset_type=identity.asset_type,
            currency=identity.currency,
            sector=identity.sector,
        )
        self.entries[key] = entry
        return entry

    async def get(self, instrument_id):
        for entry in self.entries.values():
            if entry.instrument_id == instrument_id:
                return entry
        return None

    async def find_by_natural_key(self, market: str, symbol: str):
        return self.entries.get((market, symbol))

    async def search(self, query: str, *, limit: int = 20):
        q = query.lower()
        matched = [
            entry
            for entry in self.entries.values()
            if q in entry.symbol.lower() or q in entry.name.lower() or q in entry.market.lower()
        ]
        matched.sort(key=lambda e: (e.symbol, e.market))
        return tuple(matched[:limit])


def test_instrument_identity_normalizes_market_symbol_currency() -> None:
    identity = InstrumentIdentity(
        market=" sse ",
        symbol=" 600519 ",
        name="贵州茅台",
        asset_type="equity",
        currency="cny",
        sector="Consumer",
    )
    assert identity.market == "SSE"
    assert identity.symbol == "600519"
    assert identity.asset_type == "EQUITY"
    assert identity.currency == "CNY"
    assert identity.natural_key == ("SSE", "600519")


def test_instrument_identity_rejects_empty_symbol() -> None:
    with pytest.raises(DomainError):
        InstrumentIdentity(
            market="SSE",
            symbol="  ",
            name="x",
            asset_type="EQUITY",
            currency="CNY",
            sector="",
        )


@pytest.mark.asyncio
async def test_catalog_resolve_registers_then_reuses() -> None:
    service = InstrumentCatalogService(InMemoryCatalog())
    identity = InstrumentIdentity(
        market="SZSE",
        symbol="000001",
        name="平安银行",
        asset_type="EQUITY",
        currency="CNY",
        sector="Financials",
    )
    first = await service.resolve(identity)
    second = await service.resolve(identity)
    assert first.instrument_id == second.instrument_id


@pytest.mark.asyncio
async def test_catalog_search_requires_query() -> None:
    service = InstrumentCatalogService(InMemoryCatalog())
    with pytest.raises(ApplicationError) as exc:
        await service.search("   ")
    assert exc.value.code is ApplicationErrorCode.INSTRUMENT_SEARCH_QUERY_INVALID


@pytest.mark.asyncio
async def test_catalog_get_missing_fails_closed() -> None:
    service = InstrumentCatalogService(InMemoryCatalog())
    with pytest.raises(ApplicationError) as exc:
        await service.get(uuid4())
    assert exc.value.code is ApplicationErrorCode.INSTRUMENT_NOT_FOUND
