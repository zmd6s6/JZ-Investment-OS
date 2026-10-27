"""MVP-201 real PostgreSQL receipts, immutable evidence and fail-closed reads."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from investment_os.application.instrument_catalog import InstrumentCatalogService
from investment_os.application.market_data import (
    ManualQuoteInput,
    MarketDataError,
    MarketDataRequest,
    MarketDataService,
)
from investment_os.application.portfolio_book import PortfolioBookService, PortfolioPositionInput
from investment_os.domain.instrument import InstrumentIdentity
from investment_os.infrastructure.catalog_portfolio import (
    SessionCatalogPort,
    SessionPortfolioBookPort,
)
from investment_os.infrastructure.manual_market_data import SqlManualMarketData
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    EventLogRecord,
    EvidenceRecord,
    OutboxEventRecord,
    ResearchArtifactRecord,
)
from investment_os.infrastructure.persistence.repositories import OutboxRepository

NOW = datetime(2026, 10, 27, 0, tzinfo=UTC)
pytestmark = pytest.mark.integration


async def setup(database_engine):
    sessions = async_sessionmaker(database_engine, expire_on_commit=False)
    catalog_port = SessionCatalogPort(sessions)
    catalog = InstrumentCatalogService(catalog_port)
    book = PortfolioBookService(SessionPortfolioBookPort(sessions), catalog_port)
    entry = await catalog.register(
        InstrumentIdentity(
            market="SSE",
            symbol="629201",
            name="合成行情验收",
            asset_type="EQUITY",
            currency="CNY",
            sector="Synthetic",
        )
    )
    store = SqlManualMarketData(sessions, now=lambda: NOW)
    service = MarketDataService(
        {"MANUAL_MARKET": store}, store, catalog, book, now=lambda: NOW + timedelta(days=10)
    )
    quote = ManualQuoteInput(
        request_id=uuid4(),
        instrument_id=entry.instrument_id,
        source_name="合成来源",
        source_locator="synthetic://manual-market",
        currency="CNY",
        price="15.250000000000000001",
        observed_at=NOW - timedelta(hours=1),
        effective_at=NOW - timedelta(hours=1),
        available_at=NOW - timedelta(minutes=30),
        expires_at=NOW + timedelta(days=1),
    )
    req = MarketDataRequest(
        instrument_id=entry.instrument_id,
        source="MANUAL_MARKET",
        source_name=quote.source_name,
        as_of=NOW,
    )
    return sessions, catalog, book, store, service, quote, req


async def counts(sessions):
    async with sessions() as session:
        return [
            await session.scalar(
                select(func.count()).select_from(model).where(model.created_by == "manual_market")
            )
            for model in (
                EvidenceRecord,
                ResearchArtifactRecord,
                EventLogRecord,
                AuditLogRecord,
                OutboxEventRecord,
            )
        ]


async def test_manual_quote_concurrent_same_request_has_exactly_one_atomic_effect(database_engine):
    sessions, _, _, _, service, command, req = await setup(database_engine)
    results = await asyncio.gather(*(service.save_quote(command) for _ in range(6)))
    assert all(result == results[0] for result in results)
    assert await counts(sessions) == [1, 1, 1, 1, 1]
    snapshot = await service.get_snapshot(req)
    assert snapshot.status == "AVAILABLE"
    assert snapshot.quote.price == Decimal("15.250000000000000001")
    assert snapshot.provenance.evidence_id == results[0].evidence_id
    assert snapshot.provenance.independently_verified is False
    assert snapshot.provenance.trading_grade is False
    assert snapshot.provenance.ingested_at == NOW
    with pytest.raises(MarketDataError, match="MARKET_REQUEST_CONFLICT"):
        await service.save_quote(command.model_copy(update={"price": "16"}))
    assert await counts(sessions) == [1, 1, 1, 1, 1]


async def test_new_request_same_facts_reuses_evidence_but_has_own_receipt(database_engine):
    sessions, _, _, _, service, command, _ = await setup(database_engine)
    first = await service.save_quote(command)
    second = await service.save_quote(command.model_copy(update={"request_id": uuid4()}))
    assert first.evidence_id == second.evidence_id
    assert first.request_id != second.request_id
    assert await counts(sessions) == [1, 1, 2, 2, 2]


async def test_outbox_failure_rolls_back_every_write_and_same_request_can_retry(
    database_engine, monkeypatch
):
    sessions, _, _, _, service, command, _ = await setup(database_engine)
    original = OutboxRepository.add

    async def fail(*args, **kwargs):
        raise RuntimeError("synthetic outbox failure")

    monkeypatch.setattr(OutboxRepository, "add", fail)
    with pytest.raises(RuntimeError, match="synthetic outbox"):
        await service.save_quote(command)
    assert await counts(sessions) == [0, 0, 0, 0, 0]
    monkeypatch.setattr(OutboxRepository, "add", original)
    await service.save_quote(command)
    assert await counts(sessions) == [1, 1, 1, 1, 1]


async def test_expiry_boundary_and_late_ingestion_never_forward_fill(database_engine):
    _, _, _, _, service, command, req = await setup(database_engine)
    await service.save_quote(command)
    before_ingest = await service.get_snapshot(
        req.model_copy(update={"as_of": NOW - timedelta(seconds=1)})
    )
    assert before_ingest.status == "MISSING" and before_ingest.quote is None
    expired = await service.get_snapshot(req.model_copy(update={"as_of": command.expires_at}))
    assert expired.status == "EXPIRED" and expired.quote is None
    assert expired.provenance.expires_at == command.expires_at
    fresh = await service.get_snapshot(req)
    assert fresh.status == "AVAILABLE"


async def test_latest_future_and_expired_records_do_not_fallback_to_older_price(database_engine):
    _, _, _, _, service, command, req = await setup(database_engine)
    await service.save_quote(command)
    future = command.model_copy(
        update={
            "request_id": uuid4(),
            "effective_at": NOW + timedelta(hours=1),
            "available_at": NOW + timedelta(hours=1),
            "expires_at": NOW + timedelta(days=2),
            "price": "99",
        }
    )
    await service.save_quote(future)
    result = await service.get_snapshot(req)
    assert result.status == "NOT_YET_AVAILABLE" and result.quote is None
    assert result.provenance.effective_at == future.effective_at
    latest = future.model_copy(
        update={
            "request_id": uuid4(),
            "effective_at": NOW + timedelta(hours=2),
            "available_at": NOW + timedelta(hours=2),
            "expires_at": NOW + timedelta(hours=3),
        }
    )
    await service.save_quote(latest)
    result = await service.get_snapshot(req.model_copy(update={"as_of": NOW + timedelta(hours=4)}))
    assert result.status == "EXPIRED" and result.quote is None
    missing = await service.get_snapshot(req.model_copy(update={"source_name": "另一个明确来源"}))
    assert missing.status == "MISSING" and missing.quote is None


async def test_stored_corruption_fails_closed_and_evidence_remains_immutable(database_engine):
    sessions, _, _, _, service, command, req = await setup(database_engine)
    saved = await service.save_quote(command)
    # Simulate an imported malformed row rather than bypassing append-only triggers.
    async with sessions() as session:
        original = await session.get(EvidenceRecord, saved.evidence_id)
        bad = EvidenceRecord(
            instrument_id=command.instrument_id,
            evidence_type="MARKET",
            source_name=command.source_name,
            source_locator=command.source_locator,
            source_tier="OTHER",
            observed_at=command.observed_at,
            effective_at=NOW,
            available_at=NOW,
            ingested_at=NOW,
            expires_at=command.expires_at,
            quality_score=Decimal("0"),
            freshness_status="FRESH",
            payload_json={"quote": {"price": "corrupt"}},
            content_hash="f" * 64,
            created_by="manual_market",
            correlation_id=uuid4(),
            metadata_json={"provider": "MANUAL_MARKET"},
        )
        session.add(bad)
        await session.commit()
        original.payload_json = {"corrupt": True}
        with pytest.raises(DBAPIError):
            await session.commit()
        await session.rollback()
    result = await service.get_snapshot(req)
    assert result.status == "INVALID" and result.quote is None


async def test_mixed_currency_portfolio_and_non_cny_identity_are_blocked(database_engine):
    _, catalog, book, _, service, command, req = await setup(database_engine)
    portfolio = await book.create_portfolio(
        name="合成多币种", base_currency="CNY", cash_balance=Decimal("0")
    )
    await book.record_manual_position(
        portfolio_id=portfolio.portfolio_id,
        position=PortfolioPositionInput(
            market="NASDAQ",
            symbol="SYN201",
            name="合成美元标的",
            asset_type="EQUITY",
            currency="USD",
            sector="Synthetic",
            core_quantity=Decimal("1"),
            tactical_quantity=Decimal("0"),
            average_cost=Decimal("1"),
        ),
    )
    result = await service.get_snapshot(
        req.model_copy(update={"portfolio_id": portfolio.portfolio_id})
    )
    assert result.status == "FX_REQUIRED" and result.quote is None
    other = await catalog.register(
        InstrumentIdentity(
            market="NASDAQ",
            symbol="SYN202",
            name="合成美元",
            asset_type="EQUITY",
            currency="USD",
            sector="Synthetic",
        )
    )
    with pytest.raises(MarketDataError, match="FX_REQUIRED"):
        await service.save_quote(command.model_copy(update={"instrument_id": other.instrument_id}))
    with pytest.raises(MarketDataError, match="MARKET_INSTRUMENT_NOT_FOUND"):
        await service.save_quote(command.model_copy(update={"instrument_id": uuid4()}))
