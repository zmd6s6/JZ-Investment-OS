"""Regression: CSV import audit applied rows must persist per-field values (not null).

Covers CREATED / REPLACED / UPDATED / SKIPPED after a real confirm commit,
re-read from the database and the history API adapter.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from investment_os.application.portfolio_book import (
    PortfolioBookService,
    PortfolioPositionInput,
)
from investment_os.application.portfolio_csv import PortfolioCsvImportService
from investment_os.infrastructure.catalog_portfolio import (
    SessionCatalogPort,
    SessionPortfolioBookPort,
    SqlPortfolioBookAdapter,
)
from investment_os.infrastructure.persistence.models import AuditLogRecord

CSV_HEADER = (
    "market,symbol,name,asset_type,currency,sector,core_quantity,tactical_quantity,average_cost"
)


def _services(engine: AsyncEngine):
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    catalog_port = SessionCatalogPort(factory)
    book = PortfolioBookService(SessionPortfolioBookPort(factory), catalog_port)
    csv = PortfolioCsvImportService(book, catalog_port)
    return factory, book, csv


def _entry(symbol: str, core: str, tactical: str, average: str) -> PortfolioPositionInput:
    return PortfolioPositionInput(
        market="SSE",
        symbol=symbol,
        name=f"SYN_{symbol}",
        asset_type="EQUITY",
        currency="CNY",
        sector="SYN",
        core_quantity=Decimal(core),
        tactical_quantity=Decimal(tactical),
        average_cost=Decimal(average),
    )


async def _audit_rows(factory: async_sessionmaker[AsyncSession], audit_id: UUID) -> dict:
    async with factory() as session:
        record = await session.get(AuditLogRecord, audit_id)
        assert record is not None
        applied = (record.metadata_json or {}).get("applied")
        assert isinstance(applied, list) and applied, f"applied missing: {record.metadata_json}"
        return applied[0]


async def _history_rows(factory: async_sessionmaker[AsyncSession], portfolio_id: UUID) -> dict:
    async with factory() as session:
        adapter = SqlPortfolioBookAdapter(session)
        history = await adapter.list_import_audits(portfolio_id=portfolio_id, limit=5)
        assert history and history[0]["applied"], f"history empty: {history}"
        return history[0]["applied"][0]


async def _assert_row_fields(
    row: dict,
    *,
    line_number: int,
    market: str,
    symbol: str,
    action: str,
) -> None:
    assert row.get("line_number") == line_number, row
    assert row.get("market") == market, row
    assert row.get("symbol") == symbol, row
    assert row.get("action") == action, row
    assert row.get("before") is not None or action == "CREATED", row
    assert row.get("after") is not None, row


@pytest.mark.asyncio
async def test_import_created_audit_row_fields_persist(database_engine: AsyncEngine) -> None:
    factory, book, csv = _services(database_engine)
    portfolio = await book.create_portfolio(
        name=f"SYN_audit_create_{uuid4().hex[:8]}",
        base_currency="CNY",
        cash_balance=Decimal("0"),
    )
    raw = "\n".join([CSV_HEADER, "SSE,700001,SYN_700001,EQUITY,CNY,SYN,2,1,152"])
    preview = await csv.preview(portfolio.portfolio_id, raw)
    result = await csv.confirm(
        portfolio_id=portfolio.portfolio_id,
        raw_text=raw,
        expected_preview_hash=preview.content_hash,
        expected_positions_hash=preview.positions_hash,
    )
    db_row = await _audit_rows(factory, result.audit_id)
    await _assert_row_fields(db_row, line_number=2, market="SSE", symbol="700001", action="CREATED")
    after = db_row["after"]
    assert after is not None
    assert str(after.get("core_quantity")) in {"2", "2.000000000000000000"}
    assert str(after.get("tactical_quantity")) in {"1", "1.000000000000000000"}
    assert db_row["before"] is None

    history_row = await _history_rows(factory, portfolio.portfolio_id)
    await _assert_row_fields(
        history_row, line_number=2, market="SSE", symbol="700001", action="CREATED"
    )


@pytest.mark.asyncio
async def test_import_replaced_audit_row_fields_persist(database_engine: AsyncEngine) -> None:
    factory, book, csv = _services(database_engine)
    portfolio = await book.create_portfolio(
        name=f"SYN_audit_replace_{uuid4().hex[:8]}",
        base_currency="CNY",
        cash_balance=Decimal("0"),
    )
    await book.record_manual_position(
        portfolio_id=portfolio.portfolio_id, position=_entry("700002", "8", "2", "100")
    )
    raw = "\n".join([CSV_HEADER, "SSE,700002,SYN_700002,EQUITY,CNY,SYN,2,1,152"])
    preview = await csv.preview(portfolio.portfolio_id, raw)
    result = await csv.confirm(
        portfolio_id=portfolio.portfolio_id,
        raw_text=raw,
        conflict_policy="REPLACE",
        expected_preview_hash=preview.content_hash,
        expected_positions_hash=preview.positions_hash,
    )
    db_row = await _audit_rows(factory, result.audit_id)
    await _assert_row_fields(
        db_row, line_number=2, market="SSE", symbol="700002", action="REPLACED"
    )
    before = db_row["before"]
    after = db_row["after"]
    assert before is not None
    assert str(before.get("core_quantity")).startswith("8")
    assert after is not None
    assert str(after.get("core_quantity")).startswith("2")


@pytest.mark.asyncio
async def test_import_updated_audit_row_fields_persist(database_engine: AsyncEngine) -> None:
    factory, book, csv = _services(database_engine)
    portfolio = await book.create_portfolio(
        name=f"SYN_audit_update_{uuid4().hex[:8]}",
        base_currency="CNY",
        cash_balance=Decimal("0"),
    )
    await book.record_manual_position(
        portfolio_id=portfolio.portfolio_id, position=_entry("700003", "8", "2", "100")
    )
    raw = "\n".join([CSV_HEADER, "SSE,700003,SYN_700003,EQUITY,CNY,SYN,1,1,152"])
    preview = await csv.preview(portfolio.portfolio_id, raw)
    result = await csv.confirm(
        portfolio_id=portfolio.portfolio_id,
        raw_text=raw,
        conflict_policy="UPDATE",
        expected_preview_hash=preview.content_hash,
        expected_positions_hash=preview.positions_hash,
    )
    db_row = await _audit_rows(factory, result.audit_id)
    await _assert_row_fields(db_row, line_number=2, market="SSE", symbol="700003", action="UPDATED")
    after = db_row["after"]
    assert after is not None
    # 8+1 / 2+1
    assert str(after.get("core_quantity")).startswith("9")
    assert str(after.get("tactical_quantity")).startswith("3")

    view = await book.get_portfolio(portfolio.portfolio_id)
    target = next(p for p in view.positions if p.symbol == "700003")
    assert target.core_quantity == Decimal("9")
    assert target.tactical_quantity == Decimal("3")


@pytest.mark.asyncio
async def test_import_skipped_audit_row_fields_persist(database_engine: AsyncEngine) -> None:
    factory, book, csv = _services(database_engine)
    portfolio = await book.create_portfolio(
        name=f"SYN_audit_skip_{uuid4().hex[:8]}",
        base_currency="CNY",
        cash_balance=Decimal("0"),
    )
    await book.record_manual_position(
        portfolio_id=portfolio.portfolio_id, position=_entry("700004", "8", "2", "100")
    )
    raw = "\n".join([CSV_HEADER, "SSE,700004,SYN_700004,EQUITY,CNY,SYN,1,0,152"])
    preview = await csv.preview(portfolio.portfolio_id, raw)
    result = await csv.confirm(
        portfolio_id=portfolio.portfolio_id,
        raw_text=raw,
        conflict_policy="SKIP",
        expected_preview_hash=preview.content_hash,
        expected_positions_hash=preview.positions_hash,
    )
    db_row = await _audit_rows(factory, result.audit_id)
    await _assert_row_fields(db_row, line_number=2, market="SSE", symbol="700004", action="SKIPPED")
    before = db_row["before"]
    after = db_row["after"]
    assert before is not None
    assert after is not None
    assert before == after
    assert str(before.get("core_quantity")).startswith("8")

    view = await book.get_portfolio(portfolio.portfolio_id)
    target = next(p for p in view.positions if p.symbol == "700004")
    assert target.core_quantity == Decimal("8")

    history_row = await _history_rows(factory, portfolio.portfolio_id)
    await _assert_row_fields(
        history_row, line_number=2, market="SSE", symbol="700004", action="SKIPPED"
    )
