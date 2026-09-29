"""PRODUCT-05 CSV import preview/confirm tests."""

from decimal import Decimal
from uuid import uuid4

import pytest

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.instrument_catalog import InstrumentCatalogEntry
from investment_os.application.portfolio_book import (
    PortfolioBookService,
    PortfolioPositionView,
    PortfolioView,
)
from investment_os.application.portfolio_csv import (
    PortfolioCsvImportService,
    parse_portfolio_csv,
)
from investment_os.domain.instrument import InstrumentIdentity

HEADER = (
    "market,symbol,name,asset_type,currency,sector,core_quantity,tactical_quantity,average_cost"
)
GOOD = "SSE,600519,贵州茅台,EQUITY,CNY,Consumer,10,2,1600"
BAD = "SSE,600519,贵州茅台,EQUITY,CNY,Consumer,10,2,not-a-number"
DUP = "SSE,600519,贵州茅台,EQUITY,CNY,Consumer,1,0,1600"


class InMemoryCatalog:
    def __init__(self) -> None:
        self.entries = {}

    async def upsert(self, identity: InstrumentIdentity) -> InstrumentCatalogEntry:
        key = identity.natural_key
        entry = InstrumentCatalogEntry(
            instrument_id=uuid4(),
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

    async def find_by_natural_key(self, market, symbol):
        return self.entries.get((market, symbol))

    async def search(self, query, *, limit=20):
        return tuple(self.entries.values())[:limit]


class InMemoryPortfolios:
    def __init__(self) -> None:
        self.portfolios = {}
        self.positions = {}
        self.writes = 0

    async def create_portfolio(self, *, name, base_currency, cash_balance):
        portfolio_id = uuid4()
        self.portfolios[portfolio_id] = PortfolioView(
            portfolio_id=portfolio_id,
            name=name,
            base_currency=base_currency,
            cash_balance=cash_balance,
            status="ACTIVE",
            positions=(),
        )
        return portfolio_id

    async def get_portfolio(self, portfolio_id):
        view = self.portfolios.get(portfolio_id)
        if view is None:
            return None
        positions = tuple(pos for (pid, _), pos in self.positions.items() if pid == portfolio_id)
        return PortfolioView(
            portfolio_id=view.portfolio_id,
            name=view.name,
            base_currency=view.base_currency,
            cash_balance=view.cash_balance,
            status=view.status,
            positions=positions,
        )

    async def list_portfolios(self):
        return tuple(self.portfolios.values())

    async def upsert_position(
        self, *, portfolio_id, instrument_id, core_quantity, tactical_quantity, average_cost
    ):
        self.writes += 1
        view = PortfolioPositionView(
            position_id=uuid4(),
            instrument_id=instrument_id,
            market="SSE",
            symbol="CSV",
            name="CSV",
            asset_type="EQUITY",
            currency="CNY",
            sector="",
            core_quantity=core_quantity,
            tactical_quantity=tactical_quantity,
            average_cost=average_cost,
        )
        self.positions[(portfolio_id, instrument_id)] = view
        return view

    async def set_cash_balance(self, portfolio_id, cash_balance):
        view = self.portfolios[portfolio_id]
        return PortfolioView(
            portfolio_id=view.portfolio_id,
            name=view.name,
            base_currency=view.base_currency,
            cash_balance=cash_balance,
            status=view.status,
            positions=(),
        )


def test_csv_preview_marks_valid_invalid_and_duplicate() -> None:
    preview = parse_portfolio_csv("\n".join([HEADER, GOOD, BAD, DUP]))
    assert preview.total_rows == 3
    assert len(preview.valid) == 1
    assert len(preview.invalid) == 1
    assert len(preview.duplicates) == 1
    assert preview.can_commit is False


def test_csv_preview_all_valid_can_commit() -> None:
    preview = parse_portfolio_csv("\n".join([HEADER, GOOD]))
    assert preview.can_commit is True
    assert preview.valid[0].normalized is not None
    assert preview.valid[0].normalized.core_quantity == Decimal("10")


@pytest.mark.asyncio
async def test_csv_confirm_requires_clean_preview() -> None:
    book = PortfolioBookService(InMemoryPortfolios(), InMemoryCatalog())
    service = PortfolioCsvImportService(book)
    portfolio = await book.create_portfolio(name="p", base_currency="CNY", cash_balance=0)
    with pytest.raises(ApplicationError) as exc:
        await service.confirm(
            portfolio_id=portfolio.portfolio_id, raw_text="\n".join([HEADER, BAD])
        )
    assert exc.value.code is ApplicationErrorCode.PORTFOLIO_WRITE_INVALID


@pytest.mark.asyncio
async def test_csv_confirm_writes_valid_rows_once() -> None:
    store = InMemoryPortfolios()
    book = PortfolioBookService(store, InMemoryCatalog())
    service = PortfolioCsvImportService(book)
    portfolio = await book.create_portfolio(name="p", base_currency="CNY", cash_balance=0)
    result = await service.confirm(
        portfolio_id=portfolio.portfolio_id,
        raw_text="\n".join([HEADER, GOOD]),
    )
    assert result.imported_count == 1
    assert store.writes == 1
    assert len(result.portfolio.positions) == 1
