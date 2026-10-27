"""MVP-202 actual PostgreSQL frozen reads and immutable reference-price lineage."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.instrument_catalog import InstrumentCatalogService
from investment_os.application.market_data import ManualQuoteInput, MarketDataService
from investment_os.application.portfolio_book import PortfolioBookService, PortfolioPositionInput
from investment_os.application.portfolio_valuation import PortfolioValuationService
from investment_os.infrastructure.catalog_portfolio import (
    SessionCatalogPort,
    SessionPortfolioBookPort,
)
from investment_os.infrastructure.manual_market_data import SqlManualMarketData
from investment_os.infrastructure.persistence.models import (
    EventLogRecord,
    PortfolioRecord,
    PositionRecord,
)
from investment_os.infrastructure.portfolio_valuation import SqlValuationInputs

pytestmark = pytest.mark.integration


async def prepare(database_engine):
    sessions = async_sessionmaker(database_engine, expire_on_commit=False)
    catalog = SessionCatalogPort(sessions)
    book = PortfolioBookService(SessionPortfolioBookPort(sessions), catalog)
    portfolio = await book.create_portfolio(
        name="合成估值组合", base_currency="CNY", cash_balance="103"
    )
    position = await book.record_manual_position(
        portfolio_id=portfolio.portfolio_id,
        position=PortfolioPositionInput(
            market="SSE",
            symbol="629202",
            name="合成估值标的",
            asset_type="EQUITY",
            currency="CNY",
            sector="合成行业",
            core_quantity=Decimal("2"),
            tactical_quantity=Decimal("1"),
            average_cost=Decimal("11"),
            core_average_cost=Decimal("10"),
            tactical_average_cost=Decimal("13"),
        ),
    )
    position = position.positions[0]
    store = SqlManualMarketData(sessions)
    market = MarketDataService(
        {"MANUAL_MARKET": store}, store, InstrumentCatalogService(catalog), book
    )
    now = datetime.now(UTC)
    command = ManualQuoteInput(
        request_id=uuid4(),
        instrument_id=position.instrument_id,
        source_name="合成估值来源",
        source_locator="synthetic://valuation-202",
        currency="CNY",
        price="19.25",
        observed_at=now - timedelta(hours=2),
        effective_at=now - timedelta(hours=2),
        available_at=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=1),
    )
    return sessions, book, portfolio, position, store, market, command


async def test_real_book_quotes_and_exact_nav_have_lineage_without_any_valuation_write(
    database_engine,
):
    sessions, _, portfolio, _position, store, market, command = await prepare(database_engine)
    receipt = await store.save_quote(command)
    async with sessions() as session:
        before = await session.scalar(select(func.count()).select_from(EventLogRecord))
    result = await PortfolioValuationService(SqlValuationInputs(sessions), market).get_context(
        portfolio.portfolio_id, source="MANUAL_MARKET", source_name="合成估值来源"
    )
    assert result.nav == Decimal("160.75") and result.market_value == Decimal("57.75")
    assert result.holdings[0].core_value == Decimal("38.50") and result.holdings[
        0
    ].tactical_value == Decimal("19.25")
    assert result.input_snapshot.holdings[0].core_average_cost == Decimal("10")
    assert result.input_snapshot.holdings[0].tactical_average_cost == Decimal("13")
    assert result.quotes[0].provenance.evidence_id == receipt.evidence_id
    assert result.quotes[0].provenance.content_hash == receipt.content_hash
    assert result.quotes[0].provenance.ingested_at <= result.input_snapshot.captured_at
    assert "POLICY_MISSING" in result.blockers and not result.sizing_ready
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(EventLogRecord)) == before


async def test_real_missing_expired_and_fx_boundaries_never_publish_nav(database_engine):
    sessions, book, portfolio, _, store, market, command = await prepare(database_engine)
    service = PortfolioValuationService(SqlValuationInputs(sessions), market)
    missing = await service.get_context(
        portfolio.portfolio_id, source="MANUAL_MARKET", source_name="合成估值来源"
    )
    assert missing.nav is None and "QUOTE_MISSING" in missing.blockers
    await store.save_quote(
        command.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(minutes=1)})
    )
    expired = await service.get_context(
        portfolio.portfolio_id, source="MANUAL_MARKET", source_name="合成估值来源"
    )
    assert expired.nav is None and "QUOTE_EXPIRED" in expired.blockers
    foreign = await book.create_portfolio(name="合成外币", base_currency="USD", cash_balance="10")
    fx = await service.get_context(
        foreign.portfolio_id, source="MANUAL_MARKET", source_name="合成估值来源"
    )
    assert fx.nav is None and fx.quotes == () and "FX_REQUIRED" in fx.blockers


async def test_repeatable_read_captures_cash_and_positions_before_concurrent_atomic_save(
    database_engine, monkeypatch
):
    sessions, _, portfolio, _, _, _, _ = await prepare(database_engine)
    captured = asyncio.Event()
    written = asyncio.Event()
    original = AsyncSession.get

    async def paused_get(session, entity, *args, **kwargs):
        value = await original(session, entity, *args, **kwargs)
        if entity is PortfolioRecord:
            captured.set()
            await written.wait()
        return value

    monkeypatch.setattr(AsyncSession, "get", paused_get)

    async def writer():
        await captured.wait()
        async with sessions() as session, session.begin():
            await session.execute(
                update(PortfolioRecord)
                .where(PortfolioRecord.id == portfolio.portfolio_id)
                .values(cash_balance=Decimal("77"))
            )
            await session.execute(
                update(PositionRecord)
                .where(PositionRecord.portfolio_id == portfolio.portfolio_id)
                .values(core_quantity=Decimal("8"))
            )
        written.set()

    frozen, _ = await asyncio.gather(
        SqlValuationInputs(sessions).capture(portfolio.portfolio_id), writer()
    )
    assert frozen.cash == Decimal("103")
    assert frozen.holdings[0].core_quantity == Decimal("2")
    async with sessions() as session:
        assert await session.scalar(
            select(PortfolioRecord.cash_balance).where(PortfolioRecord.id == portfolio.portfolio_id)
        ) == Decimal("77")


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("test", "POLICY_TEST_DEFAULT"),
        ("missing-version", "POLICY_VERSION_MISSING"),
        ("ambiguous", "POLICY_AMBIGUOUS"),
        ("invalid", "POLICY_CONFIG_INVALID"),
    ],
)
async def test_policy_versions_are_pinned_and_never_silently_defaulted(
    database_engine, mode, reason
):
    import json
    from pathlib import Path

    from investment_os.infrastructure.persistence.models import (
        InvestmentPolicyRecord,
        InvestmentPolicyVersionRecord,
    )

    sessions, _, portfolio, _, _, market, _ = await prepare(database_engine)
    identifier = uuid4()
    version_id = uuid4()
    now = datetime.now(UTC)
    config = json.loads(
        await asyncio.to_thread(
            Path("config/investment-policy.test-default.json").read_text, encoding="utf-8"
        )
    )
    async with sessions() as session, session.begin():
        record = InvestmentPolicyRecord(
            id=identifier,
            name="TEST_SYNTHETIC" if mode == "test" else "Synthetic",
            status="ACTIVE",
            current_version_id=None,
            version=1,
            created_by="pytest",
            correlation_id=uuid4(),
            schema_version="1.0",
            metadata_json={},
        )
        session.add(record)
        await session.flush()
        if mode != "missing-version":
            version = InvestmentPolicyVersionRecord(
                id=version_id,
                policy_id=identifier,
                version=7,
                config_json={} if mode == "invalid" else config,
                content_hash="a" * 64,
                effective_from=now - timedelta(hours=1),
                approved_by=None,
                approved_at=None,
                created_by="pytest",
                correlation_id=uuid4(),
                schema_version="1.0",
                metadata_json={},
            )
            session.add(version)
            await session.flush()
            record.current_version_id = version_id
        if mode == "ambiguous":
            session.add(
                InvestmentPolicyRecord(
                    id=uuid4(),
                    name="OtherSynthetic",
                    status="ACTIVE",
                    current_version_id=None,
                    version=1,
                    created_by="pytest",
                    correlation_id=uuid4(),
                    schema_version="1.0",
                    metadata_json={},
                )
            )
    context = await PortfolioValuationService(SqlValuationInputs(sessions), market).get_context(
        portfolio.portfolio_id, source="MANUAL_MARKET", source_name="合成估值来源"
    )
    assert context.input_snapshot.policy.reason_code == reason
    assert reason in context.blockers and not context.sizing_ready
    if mode not in {"missing-version", "ambiguous"}:
        assert context.input_snapshot.policy.version_id == version_id
        assert context.input_snapshot.policy.version == 7
        assert context.input_snapshot.policy.content_hash == "a" * 64
