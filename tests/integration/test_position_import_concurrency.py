"""Named concurrency regression tests for portfolio position import (R1).

Uses two real database session factories and a deterministic synchronization
hook. The hook only orders execution; production lock/CAS/write/commit logic
still runs unchanged.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.instrument_catalog import InstrumentCatalogService
from investment_os.application.portfolio_book import (
    PortfolioBookService,
    PortfolioPositionInput,
)
from investment_os.application.portfolio_csv import PortfolioCsvImportService
from investment_os.infrastructure.catalog_portfolio import (
    SessionCatalogPort,
    SessionPortfolioBookPort,
    SqlInstrumentCatalogAdapter,
)

CSV_HEADER = (
    "market,symbol,name,asset_type,currency,sector,core_quantity,tactical_quantity,average_cost"
)


def _services(engine: AsyncEngine):
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    catalog_port = SessionCatalogPort(factory)
    catalog = InstrumentCatalogService(catalog_port)
    book = PortfolioBookService(SessionPortfolioBookPort(factory), catalog_port)
    csv = PortfolioCsvImportService(book, catalog_port)
    return factory, catalog, book, csv


def _entry(symbol: str, core: str, tactical: str, average: str) -> PortfolioPositionInput:
    return PortfolioPositionInput(
        market="SSE",
        symbol=symbol,
        name=f"SYNTHETIC_{symbol}",
        asset_type="EQUITY",
        currency="CNY",
        sector="SYNTHETIC",
        core_quantity=Decimal(core),
        tactical_quantity=Decimal(tactical),
        average_cost=Decimal(average),
    )


async def _make_portfolio(book: PortfolioBookService, name: str):
    return await book.create_portfolio(name=name, base_currency="CNY", cash_balance=Decimal("1000"))


@pytest.mark.asyncio
async def test_import_rejects_when_preview_then_manual_edit_before_confirm(
    database_engine: AsyncEngine,
) -> None:
    _factory, _catalog, book, csv = _services(database_engine)
    portfolio = await _make_portfolio(book, f"SYN_r1_preedit_{uuid4().hex[:8]}")
    pid = portfolio.portfolio_id
    await book.record_manual_position(portfolio_id=pid, position=_entry("610001", "9", "3", "120"))

    raw = "\n".join([CSV_HEADER, "SSE,610001,SYNTHETIC_610001,EQUITY,CNY,SYNTHETIC,2,1,152"])
    preview = await csv.preview(pid, raw)
    await book.record_manual_position(portfolio_id=pid, position=_entry("610001", "40", "5", "200"))

    with pytest.raises(ApplicationError) as exc:
        await csv.confirm(
            portfolio_id=pid,
            raw_text=raw,
            conflict_policy="REPLACE",
            expected_preview_hash=preview.content_hash,
            expected_positions_hash=preview.positions_hash,
        )
    assert exc.value.code is ApplicationErrorCode.PORTFOLIO_WRITE_INVALID

    after = await book.get_portfolio(pid)
    target = next(p for p in after.positions if p.symbol == "610001")
    assert target.core_quantity == Decimal("40")
    assert target.average_cost == Decimal("200")


@pytest.mark.asyncio
async def test_import_new_target_rejects_concurrent_manual_create_on_empty_portfolio(
    database_engine: AsyncEngine,
) -> None:
    _factory, _catalog, book, csv = _services(database_engine)
    portfolio = await _make_portfolio(book, f"SYN_r1_empty_{uuid4().hex[:8]}")
    pid = portfolio.portfolio_id

    raw = "\n".join([CSV_HEADER, "SSE,620001,SYNTHETIC_620001,EQUITY,CNY,SYNTHETIC,2,1,152"])
    preview = await csv.preview(pid, raw)

    paused = asyncio.Event()
    resume = asyncio.Event()
    original_upsert = SqlInstrumentCatalogAdapter.upsert
    import_task_name = "import_task"

    async def scheduling_hook(self, identity):
        if (
            asyncio.current_task() is not None
            and asyncio.current_task().get_name() == import_task_name
        ):
            paused.set()
            await resume.wait()
        return await original_upsert(self, identity)

    SqlInstrumentCatalogAdapter.upsert = scheduling_hook  # type: ignore[method-assign]
    try:
        import_task = asyncio.create_task(
            csv.confirm(
                portfolio_id=pid,
                raw_text=raw,
                expected_preview_hash=preview.content_hash,
                expected_positions_hash=preview.positions_hash,
            ),
            name=import_task_name,
        )
        await asyncio.wait_for(paused.wait(), timeout=10)

        # Concurrent manual create of the same target after hash check, before import write.
        # With portfolio lock held by import, this waits; after import commits it may run.
        manual_task = asyncio.create_task(
            book.record_manual_position(
                portfolio_id=pid, position=_entry("620001", "40", "5", "200")
            ),
            name="manual_task",
        )
        await asyncio.sleep(0.05)
        assert not manual_task.done(), "manual write should wait on portfolio lock"
        resume.set()
        await asyncio.wait_for(import_task, timeout=10)
        await asyncio.wait_for(manual_task, timeout=10)
    finally:
        SqlInstrumentCatalogAdapter.upsert = original_upsert  # type: ignore[method-assign]
        resume.set()

    after = await book.get_portfolio(pid)
    target = next(p for p in after.positions if p.symbol == "620001")
    # Manual write ran after import and must remain authoritative (not lost to stale import).
    assert target.core_quantity == Decimal("40")
    assert target.average_cost == Decimal("200")


@pytest.mark.asyncio
async def test_import_new_target_with_unrelated_existing_position_serialized(
    database_engine: AsyncEngine,
) -> None:
    _factory, _catalog, book, csv = _services(database_engine)
    portfolio = await _make_portfolio(book, f"SYN_r1_unrel_{uuid4().hex[:8]}")
    pid = portfolio.portfolio_id
    await book.record_manual_position(portfolio_id=pid, position=_entry("620002", "8", "2", "100"))

    raw = "\n".join([CSV_HEADER, "SSE,620003,SYNTHETIC_620003,EQUITY,CNY,SYNTHETIC,2,1,152"])
    preview = await csv.preview(pid, raw)

    paused = asyncio.Event()
    resume = asyncio.Event()
    original_upsert = SqlInstrumentCatalogAdapter.upsert

    async def scheduling_hook(self, identity):
        task = asyncio.current_task()
        if task is not None and task.get_name() == "import_task":
            paused.set()
            await resume.wait()
        return await original_upsert(self, identity)

    SqlInstrumentCatalogAdapter.upsert = scheduling_hook  # type: ignore[method-assign]
    try:
        import_task = asyncio.create_task(
            csv.confirm(
                portfolio_id=pid,
                raw_text=raw,
                expected_preview_hash=preview.content_hash,
                expected_positions_hash=preview.positions_hash,
            ),
            name="import_task",
        )
        await asyncio.wait_for(paused.wait(), timeout=10)
        manual_task = asyncio.create_task(
            book.record_manual_position(
                portfolio_id=pid, position=_entry("620003", "40", "5", "200")
            ),
            name="manual_task",
        )
        await asyncio.sleep(0.05)
        assert not manual_task.done()
        resume.set()
        await asyncio.wait_for(import_task, timeout=10)
        await asyncio.wait_for(manual_task, timeout=10)
    finally:
        SqlInstrumentCatalogAdapter.upsert = original_upsert  # type: ignore[method-assign]
        resume.set()

    after = await book.get_portfolio(pid)
    target = next(p for p in after.positions if p.symbol == "620003")
    assert target.core_quantity == Decimal("40")
    # Unrelated position must be untouched.
    unrelated = next(p for p in after.positions if p.symbol == "620002")
    assert unrelated.core_quantity == Decimal("8")


@pytest.mark.asyncio
async def test_import_existing_target_rejects_stale_snapshot_and_preserves_manual(
    database_engine: AsyncEngine,
) -> None:
    _factory, _catalog, book, csv = _services(database_engine)
    portfolio = await _make_portfolio(book, f"SYN_r1_exist_{uuid4().hex[:8]}")
    pid = portfolio.portfolio_id
    await book.record_manual_position(portfolio_id=pid, position=_entry("620004", "9", "3", "120"))

    raw = "\n".join([CSV_HEADER, "SSE,620004,SYNTHETIC_620004,EQUITY,CNY,SYNTHETIC,2,1,152"])
    preview = await csv.preview(pid, raw)
    await book.record_manual_position(portfolio_id=pid, position=_entry("620004", "40", "5", "200"))

    with pytest.raises(ApplicationError) as exc:
        await csv.confirm(
            portfolio_id=pid,
            raw_text=raw,
            conflict_policy="REPLACE",
            expected_preview_hash=preview.content_hash,
            expected_positions_hash=preview.positions_hash,
        )
    assert exc.value.code is ApplicationErrorCode.PORTFOLIO_WRITE_INVALID

    after = await book.get_portfolio(pid)
    target = next(p for p in after.positions if p.symbol == "620004")
    assert target.core_quantity == Decimal("40")
    assert target.average_cost == Decimal("200")


@pytest.mark.asyncio
async def test_position_version_increments_and_cas_rejects_stale_version(
    database_engine: AsyncEngine,
) -> None:
    _factory, catalog, book, _csv = _services(database_engine)
    portfolio = await _make_portfolio(book, f"SYN_r1_ver_{uuid4().hex[:8]}")
    pid = portfolio.portfolio_id
    from investment_os.domain.instrument import InstrumentIdentity

    entry = await catalog.register(
        InstrumentIdentity(
            market="SSE",
            symbol="620005",
            name="SYNTHETIC_620005",
            asset_type="EQUITY",
            currency="CNY",
            sector="SYNTHETIC",
        )
    )
    identity = entry
    adapter_factory = async_sessionmaker(
        database_engine, expire_on_commit=False, class_=AsyncSession
    )
    from investment_os.infrastructure.catalog_portfolio import SqlPortfolioBookAdapter

    async with adapter_factory() as session:
        adapter = SqlPortfolioBookAdapter(session)
        first = await adapter.upsert_position(
            portfolio_id=pid,
            instrument_id=identity.instrument_id,
            core_quantity=Decimal("1"),
            tactical_quantity=Decimal("0"),
            average_cost=Decimal("10"),
        )
        assert first.operation == "MANUAL"
        await session.commit()

    async with adapter_factory() as session:
        adapter = SqlPortfolioBookAdapter(session)
        snapshot = await adapter._read_position_fields(
            portfolio_id=pid, instrument_id=identity.instrument_id
        )
        assert snapshot is not None
        version = int(snapshot["version"])
        second = await adapter.upsert_position(
            portfolio_id=pid,
            instrument_id=identity.instrument_id,
            core_quantity=Decimal("2"),
            tactical_quantity=Decimal("0"),
            average_cost=Decimal("11"),
            expected_version=version,
        )
        assert second.core_quantity == Decimal("2")
        await session.commit()

    async with adapter_factory() as session:
        adapter = SqlPortfolioBookAdapter(session)
        snapshot = await adapter._read_position_fields(
            portfolio_id=pid, instrument_id=identity.instrument_id
        )
        assert snapshot is not None
        assert int(snapshot["version"]) == version + 1
        with pytest.raises(ApplicationError) as exc:
            await adapter.upsert_position(
                portfolio_id=pid,
                instrument_id=identity.instrument_id,
                core_quantity=Decimal("3"),
                tactical_quantity=Decimal("0"),
                average_cost=Decimal("12"),
                expected_version=version,
            )
        assert exc.value.code is ApplicationErrorCode.POSITION_VERSION_CONFLICT
        await session.rollback()


@pytest.mark.asyncio
async def test_import_batch_rolls_back_entirely_on_conflict(
    database_engine: AsyncEngine,
) -> None:
    _factory, _catalog, book, csv = _services(database_engine)
    portfolio = await _make_portfolio(book, f"SYN_r1_batch_{uuid4().hex[:8]}")
    pid = portfolio.portfolio_id
    await book.record_manual_position(portfolio_id=pid, position=_entry("620006", "1", "0", "10"))

    raw = "\n".join(
        [
            CSV_HEADER,
            "SSE,620006,SYNTHETIC_620006,EQUITY,CNY,SYNTHETIC,2,1,152",
            "SSE,620007,SYNTHETIC_620007,EQUITY,CNY,SYNTHETIC,3,0,11",
        ]
    )
    preview = await csv.preview(pid, raw)
    await book.record_manual_position(portfolio_id=pid, position=_entry("620006", "40", "5", "200"))

    before_count = len((await book.get_portfolio(pid)).positions)
    with pytest.raises(ApplicationError) as exc:
        await csv.confirm(
            portfolio_id=pid,
            raw_text=raw,
            conflict_policy="REPLACE",
            expected_preview_hash=preview.content_hash,
            expected_positions_hash=preview.positions_hash,
        )
    assert exc.value.code is ApplicationErrorCode.PORTFOLIO_WRITE_INVALID

    after = await book.get_portfolio(pid)
    assert len(after.positions) == before_count
    assert all(p.symbol != "620007" for p in after.positions)
    target = next(p for p in after.positions if p.symbol == "620006")
    assert target.core_quantity == Decimal("40")
