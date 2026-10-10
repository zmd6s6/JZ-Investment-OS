"""Application boundary for instrument identity, search, and normalization."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.domain.instrument import InstrumentIdentity


@dataclass(frozen=True, slots=True)
class InstrumentCatalogEntry:
    instrument_id: UUID
    market: str
    symbol: str
    name: str
    asset_type: str
    currency: str
    sector: str


class InstrumentCatalogPort(Protocol):
    """Persistence port for the local instrument catalog."""

    async def upsert(self, identity: InstrumentIdentity) -> InstrumentCatalogEntry: ...

    async def get(self, instrument_id: UUID) -> InstrumentCatalogEntry | None: ...

    async def find_by_natural_key(
        self, market: str, symbol: str
    ) -> InstrumentCatalogEntry | None: ...

    async def search(
        self, query: str, *, limit: int = 20
    ) -> tuple[InstrumentCatalogEntry, ...]: ...


class InstrumentCatalogService:
    def __init__(self, catalog: InstrumentCatalogPort) -> None:
        self._catalog = catalog

    async def register(self, identity: InstrumentIdentity) -> InstrumentCatalogEntry:
        return await self._catalog.upsert(identity)

    async def get(self, instrument_id: UUID) -> InstrumentCatalogEntry:
        entry = await self._catalog.get(instrument_id)
        if entry is None:
            raise ApplicationError(
                ApplicationErrorCode.INSTRUMENT_NOT_FOUND,
                "instrument is not in the local catalog",
                details={"instrument_id": str(instrument_id)},
            )
        return entry

    async def resolve(self, identity: InstrumentIdentity) -> InstrumentCatalogEntry:
        """Return the canonical catalog entry, registering it when unknown."""

        existing = await self._catalog.find_by_natural_key(identity.market, identity.symbol)
        if existing is not None:
            return existing
        return await self._catalog.upsert(identity)

    async def search(self, query: str, *, limit: int = 20) -> tuple[InstrumentCatalogEntry, ...]:
        cleaned = query.strip()
        if not cleaned:
            raise ApplicationError(
                ApplicationErrorCode.INSTRUMENT_SEARCH_QUERY_INVALID,
                "instrument search query must not be empty",
            )
        bounded = min(max(limit, 1), 50)
        return await self._catalog.search(cleaned, limit=bounded)
