"""Application boundary for Watchlist membership (PRODUCT-05 write path)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.instrument_catalog import InstrumentCatalogPort
from investment_os.domain.instrument import InstrumentIdentity


@dataclass(frozen=True, slots=True)
class WatchlistItemView:
    watchlist_item_id: UUID
    instrument_id: UUID
    market: str
    symbol: str
    name: str
    asset_type: str
    currency: str
    sector: str
    added_at: datetime
    # Optional product fields; "not provided" is represented as None and must not be faked.
    lifecycle_state: str | None
    thesis_state: str | None
    data_freshness_as_of: datetime | None
    data_freshness_status: str | None
    next_monitoring_condition: str | None


class WatchlistPort(Protocol):
    async def add(
        self,
        *,
        instrument_id: UUID,
        added_at: datetime,
    ) -> WatchlistItemView: ...

    async def remove(self, *, instrument_id: UUID) -> bool: ...

    async def list_items(self) -> tuple[WatchlistItemView, ...]: ...

    async def contains(self, instrument_id: UUID) -> bool: ...


class WatchlistService:
    def __init__(
        self,
        watchlist: WatchlistPort,
        catalog: InstrumentCatalogPort,
    ) -> None:
        self._watchlist = watchlist
        self._catalog = catalog

    async def add_instrument(self, identity: InstrumentIdentity) -> WatchlistItemView:
        entry = await self._catalog.upsert(identity)
        if await self._watchlist.contains(entry.instrument_id):
            items = await self._watchlist.list_items()
            for item in items:
                if item.instrument_id == entry.instrument_id:
                    return item
            raise ApplicationError(
                ApplicationErrorCode.WATCHLIST_WRITE_INVALID,
                "watchlist membership lookup failed after duplicate add",
            )
        return await self._watchlist.add(
            instrument_id=entry.instrument_id,
            added_at=datetime.now(UTC),
        )

    async def remove_instrument(self, *, market: str, symbol: str) -> bool:
        from investment_os.domain.instrument import normalize_market, normalize_symbol

        entry = await self._catalog.find_by_natural_key(
            normalize_market(market), normalize_symbol(symbol)
        )
        if entry is None:
            return False
        return await self._watchlist.remove(instrument_id=entry.instrument_id)

    async def list_items(self) -> tuple[WatchlistItemView, ...]:
        return await self._watchlist.list_items()
