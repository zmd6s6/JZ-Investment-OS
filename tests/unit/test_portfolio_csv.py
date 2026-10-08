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
        self.audit_calls = []

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
        self,
        *,
        portfolio_id,
        instrument_id,
        core_quantity,
        tactical_quantity,
        average_cost,
        core_reason="",
        tactical_reason="",
        operation="MANUAL",
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
            core_reason=core_reason,
            tactical_reason=tactical_reason,
            operation=operation,
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

    async def record_import_audit(self, *, portfolio_id, conflict_policy, applied, import_hash=""):
        self.audit_calls.append(
            {
                "portfolio_id": portfolio_id,
                "conflict_policy": conflict_policy,
                "applied": applied,
                "import_hash": import_hash,
            }
        )
        return uuid4()

    async def find_import_audit(self, *, portfolio_id, import_hash):
        for call in self.audit_calls:
            if call.get("import_hash") == import_hash:
                return uuid4()
        return None

    async def apply_import_batch(
        self, *, portfolio_id, import_hash, conflict_policy, items, applied
    ):
        self.writes += len(items)
        for item in items:
            identity = item["identity"]
            self.positions[(portfolio_id, id(identity))] = PortfolioPositionView(
                position_id=uuid4(),
                instrument_id=uuid4(),
                market=identity.market,
                symbol=identity.symbol,
                name=identity.name,
                asset_type=identity.asset_type,
                currency=identity.currency,
                sector=identity.sector,
                core_quantity=item["core_quantity"],
                tactical_quantity=item["tactical_quantity"],
                average_cost=item["average_cost"],
            )
        audit_id = uuid4()
        self.audit_calls.append(
            {
                "audit_id": audit_id,
                "portfolio_id": portfolio_id,
                "conflict_policy": conflict_policy,
                "applied": applied,
                "import_hash": import_hash,
            }
        )
        return audit_id


def test_csv_preview_marks_valid_invalid_and_duplicate() -> None:
    preview = parse_portfolio_csv("\n".join([HEADER, GOOD, BAD, DUP]))
    assert preview.total_rows == 3
    assert len(preview.valid) == 1
    assert len(preview.invalid) == 1
    assert len(preview.duplicates) == 1
    assert preview.can_commit is False


def test_csv_preview_flags_existing_portfolio_conflicts() -> None:
    existing = {
        ("SSE", "600519"): {
            "core_quantity": "100",
            "tactical_quantity": "0",
            "average_cost": "10",
            "name": "贵州茅台",
        }
    }
    preview = parse_portfolio_csv("\n".join([HEADER, GOOD]), existing=existing)
    assert preview.valid == ()
    assert len(preview.conflicts) == 1
    assert preview.requires_conflict_policy is True
    assert preview.conflicts[0].existing_core_quantity == "100"
    assert preview.can_commit is True  # commit allowed only with explicit policy later


def test_csv_preview_all_valid_can_commit() -> None:
    preview = parse_portfolio_csv("\n".join([HEADER, GOOD]))
    assert preview.can_commit is True
    assert preview.requires_conflict_policy is False
    assert preview.valid[0].normalized is not None
    assert preview.valid[0].normalized.core_quantity == Decimal("10")


@pytest.mark.asyncio
async def test_csv_confirm_requires_clean_preview() -> None:
    book = PortfolioBookService(InMemoryPortfolios(), InMemoryCatalog())
    service = PortfolioCsvImportService(book, InMemoryCatalog())
    portfolio = await book.create_portfolio(name="p", base_currency="CNY", cash_balance=0)
    with pytest.raises(ApplicationError) as exc:
        await service.confirm(
            portfolio_id=portfolio.portfolio_id, raw_text="\n".join([HEADER, BAD])
        )
    assert exc.value.code is ApplicationErrorCode.PORTFOLIO_WRITE_INVALID


@pytest.mark.asyncio
async def test_csv_confirm_requires_conflict_policy_and_never_silent_overwrite() -> None:
    store = InMemoryPortfolios()
    book = PortfolioBookService(store, InMemoryCatalog())
    service = PortfolioCsvImportService(book, InMemoryCatalog())
    portfolio = await book.create_portfolio(name="p", base_currency="CNY", cash_balance=0)

    async def fake_existing(_portfolio_id):
        return {
            ("SSE", "600519"): {
                "core_quantity": "100",
                "tactical_quantity": "0",
                "average_cost": "10",
                "name": "贵州茅台",
            }
        }

    service._existing_map = fake_existing  # type: ignore[method-assign]
    with pytest.raises(ApplicationError) as exc:
        await service.confirm(
            portfolio_id=portfolio.portfolio_id, raw_text="\n".join([HEADER, GOOD])
        )
    assert exc.value.code is ApplicationErrorCode.PORTFOLIO_WRITE_CONFLICT_POLICY_REQUIRED

    result = await service.confirm(
        portfolio_id=portfolio.portfolio_id,
        raw_text="\n".join([HEADER, GOOD]),
        conflict_policy="SKIP",
    )
    assert result.imported_count == 0
    assert result.skipped_count >= 1
    assert store.audit_calls and store.audit_calls[-1]["conflict_policy"] == "SKIP"


@pytest.mark.asyncio
async def test_csv_confirm_writes_valid_rows_once() -> None:
    store = InMemoryPortfolios()
    book = PortfolioBookService(store, InMemoryCatalog())
    service = PortfolioCsvImportService(book, InMemoryCatalog())
    portfolio = await book.create_portfolio(name="p", base_currency="CNY", cash_balance=0)
    result = await service.confirm(
        portfolio_id=portfolio.portfolio_id,
        raw_text="\n".join([HEADER, GOOD]),
    )
    assert result.imported_count == 1
    assert store.writes == 1
    assert len(result.portfolio.positions) == 1
    assert store.audit_calls
