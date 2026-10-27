"""MVP-402 actual SQL + manual market evidence + deterministic production use case."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from investment_os.application.instrument_catalog import InstrumentCatalogService
from investment_os.application.market_data import ManualQuoteInput, MarketDataService
from investment_os.application.opportunities import (
    FunnelQuery,
    ManualScreenFacts,
    OpportunityError,
    OpportunityService,
)
from investment_os.application.portfolio_book import PortfolioBookService
from investment_os.domain.instrument import InstrumentIdentity
from investment_os.infrastructure.catalog_portfolio import (
    SessionCatalogPort,
    SessionPortfolioBookPort,
)
from investment_os.infrastructure.manual_market_data import SqlManualMarketData
from investment_os.infrastructure.opportunities import LocalExplicitUniverse, SqlOpportunityStore
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    EventLogRecord,
    EvidenceRecord,
    OutboxEventRecord,
    ResearchArtifactRecord,
)
from investment_os.infrastructure.persistence.repositories import OutboxRepository

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 27, tzinfo=UTC)


async def setup(database_engine, count=1):
    sessions = async_sessionmaker(database_engine, expire_on_commit=False)
    catalog_port = SessionCatalogPort(sessions)
    catalog = InstrumentCatalogService(catalog_port)
    quotes = SqlManualMarketData(sessions, now=lambda: NOW)
    market = MarketDataService(
        {"MANUAL_MARKET": quotes},
        quotes,
        catalog,
        PortfolioBookService(SessionPortfolioBookPort(sessions), catalog_port),
        now=lambda: NOW + timedelta(days=1),
    )
    store = SqlOpportunityStore(sessions, now=lambda: NOW)
    service = OpportunityService(
        LocalExplicitUniverse(catalog), store, market, store, now=lambda: NOW
    )
    commands = []
    for index in range(count):
        entry = await catalog.register(
            InstrumentIdentity(
                market="SSE",
                symbol=str(629402 + index),
                name="合成研究" + str(index),
                asset_type="EQUITY",
                currency="CNY",
                sector="Synthetic",
            )
        )
        quote = await quotes.save_quote(
            ManualQuoteInput(
                request_id=uuid4(),
                instrument_id=entry.instrument_id,
                source_name="合成行情",
                source_locator="synthetic://quote/" + str(index),
                currency="CNY",
                price="10",
                observed_at=NOW - timedelta(hours=1),
                effective_at=NOW - timedelta(hours=1),
                available_at=NOW - timedelta(hours=1),
                expires_at=NOW + timedelta(days=1),
            )
        )
        command = ManualScreenFacts(
            request_id=uuid4(),
            instrument_id=entry.instrument_id,
            source_name="合成年报",
            source_locator="synthetic://financial/" + str(index),
            observed_at=NOW - timedelta(days=2),
            effective_at=NOW - timedelta(days=2),
            available_at=NOW - timedelta(days=1),
            expires_at=NOW + timedelta(days=1),
            previous_close_at=NOW - timedelta(days=2),
            revenue_current="100",
            revenue_previous="80",
            net_income="20",
            annual_diluted_eps="0.2",
            previous_close="8",
            fiscal_year=2025,
            financial_basis="CALENDAR_YEAR_CONSOLIDATED_CNY",
            net_income_basis="ATTRIBUTABLE_TO_ORDINARY_SHAREHOLDERS",
            quote_evidence_id=quote.evidence_id,
            same_share_basis=True,
            suspended=False,
            industry="Synthetic",
        )
        commands.append(command)
    query = FunnelQuery(
        request_id=uuid4(),
        instrument_ids=tuple(c.instrument_id for c in commands),
        scope_name="本地有限合成范围",
        scope_locator="synthetic://scope",
        quote_source_name="合成行情",
        fact_source_name="合成年报",
        as_of=NOW,
        candidate_limit=1,
        min_profit_margin="0.1",
        min_revenue_growth="0.1",
        max_pe="60",
        min_price_change="0",
    )
    return sessions, store, service, commands, query


async def counts(sessions):
    async with sessions() as session:
        return [
            await session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.created_by == "opportunity_funnel")
            )
            for model in (
                EvidenceRecord,
                ResearchArtifactRecord,
                EventLogRecord,
                AuditLogRecord,
                OutboxEventRecord,
            )
        ]


async def test_real_facts_quote_funnel_returns_stable_bounded_candidates_and_persistent_trace(
    database_engine,
):
    sessions, store, service, commands, query = await setup(database_engine, 3)
    for command in commands:
        await service.save_facts(command)
    run = await service.run(query)
    assert run.candidate_ids == (commands[0].instrument_id,)
    assert run.rows[0].features == {
        "profit_margin": "0.2",
        "revenue_growth": "0.25",
        "pe": "50",
        "price_change": "0.25",
    }
    assert all(len(row.evidence_ids) == 2 for row in run.rows)
    assert run.market_universe == "NOT_PROVIDED" and run.deep_research == "NOT_PROVIDED"
    assert not run.auto_trade and not run.independently_verified
    assert all(row.lifecycle_state is None for row in run.rows)
    assert run.rows[1].stages[-1].reason == "CANDIDATE_LIMIT_REACHED"
    assert await store.get_run(run.run_id) == run
    assert (await store.list_runs())[0] == run
    assert await counts(sessions) == [3, 3, 4, 4, 4]


async def test_concurrent_fact_and_run_replays_have_one_effect_and_conflict_rejects(
    database_engine,
):
    sessions, _, service, commands, query = await setup(database_engine)
    receipts = await asyncio.gather(*(service.save_facts(commands[0]) for _ in range(4)))
    assert all(r == receipts[0] for r in receipts)
    runs = await asyncio.gather(*(service.run(query) for _ in range(4)))
    assert all(r == runs[0] for r in runs)
    assert await counts(sessions) == [1, 1, 2, 2, 2]
    with pytest.raises(OpportunityError, match="REQUEST_CONTENT_CONFLICT"):
        await service.run(query.model_copy(update={"max_pe": "100"}))
    with pytest.raises(OpportunityError, match="REQUEST_CONTENT_CONFLICT"):
        await service.save_facts(commands[0].model_copy(update={"net_income": "100"}))
    assert await counts(sessions) == [1, 1, 2, 2, 2]


async def test_outbox_fault_rolls_back_fact_and_run_then_same_request_retries(
    database_engine, monkeypatch
):
    sessions, _, service, commands, query = await setup(database_engine)
    original = OutboxRepository.add

    async def fail(*args, **kwargs):
        raise RuntimeError("synthetic outbox failure")

    monkeypatch.setattr(OutboxRepository, "add", fail)
    with pytest.raises(RuntimeError):
        await service.save_facts(commands[0])
    assert await counts(sessions) == [0, 0, 0, 0, 0]
    monkeypatch.setattr(OutboxRepository, "add", original)
    await service.save_facts(commands[0])
    monkeypatch.setattr(OutboxRepository, "add", fail)
    with pytest.raises(RuntimeError):
        await service.run(query)
    assert await counts(sessions) == [1, 1, 1, 1, 1]
    monkeypatch.setattr(OutboxRepository, "add", original)
    await service.run(query)
    assert await counts(sessions) == [1, 1, 2, 2, 2]


async def test_missing_facts_expiry_and_new_failed_facts_never_rewrite_old_run(database_engine):
    _, store, service, commands, query = await setup(database_engine)
    missing = await service.run(query)
    assert not missing.candidate_ids and missing.status == "DEGRADED"
    await service.save_facts(commands[0])
    normal = await service.run(query.model_copy(update={"request_id": uuid4()}))
    assert normal.candidate_ids
    failed = commands[0].model_copy(
        update={
            "request_id": uuid4(),
            "net_income": "1",
            "effective_at": NOW - timedelta(minutes=30),
            "available_at": NOW - timedelta(minutes=30),
        }
    )
    await service.save_facts(failed)
    rejected = await service.run(query.model_copy(update={"request_id": uuid4()}))
    assert not rejected.candidate_ids and rejected.rows[0].stages[1].status == "REJECTED"
    assert await store.get_run(normal.run_id) == normal
    assert await store.get_run(missing.run_id) == missing
    expired = await store.get_facts(
        commands[0].instrument_id, commands[0].source_name, commands[0].expires_at
    )
    assert expired.status == "EXPIRED"
    before_ingest = await store.get_facts(
        commands[0].instrument_id, commands[0].source_name, NOW - timedelta(seconds=1)
    )
    assert before_ingest.status == "MISSING"


async def test_ambiguous_share_or_annual_basis_is_a_real_visible_missing_gate(database_engine):
    _, _, service, commands, query = await setup(database_engine)
    await service.save_facts(commands[0].model_copy(update={"quote_evidence_id": uuid4()}))
    run = await service.run(query)
    assert not run.candidate_ids
    growth = next(stage for stage in run.rows[0].stages if stage.stage == "GROWTH_VALUATION")
    assert growth.status == "MISSING" and "quote_evidence_id_matches" in growth.missing_fields


async def test_real_api_facts_run_receipt_auth_and_historical_read(database_engine):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from investment_os.api.opportunity_routes import opportunity_router
    from investment_os.api.write_auth import WriteApiAuthMiddleware

    _, _, service, commands, query = await setup(database_engine)
    app = FastAPI()
    app.include_router(opportunity_router(service))
    app.add_middleware(WriteApiAuthMiddleware, token="synthetic-opportunity-api")
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        assert (
            await client.post(
                "/api/v1/opportunities/facts", json=commands[0].model_dump(mode="json")
            )
        ).status_code == 401
        headers = {"Authorization": "Bearer synthetic-opportunity-api"}
        receipt = await client.post(
            "/api/v1/opportunities/facts", headers=headers, json=commands[0].model_dump(mode="json")
        )
        assert receipt.status_code == 200
        response = await client.post(
            "/api/v1/opportunities/runs", headers=headers, json=query.model_dump(mode="json")
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["candidate_ids"] == [str(commands[0].instrument_id)]
        assert payload["rows"][0]["features"]["pe"] == "50"
        assert (
            await client.get("/api/v1/opportunities/runs/" + payload["run_id"])
        ).json() == payload
        assert (await client.get("/api/v1/opportunities/runs")).json()[0] == payload
        bad = await client.post(
            "/api/v1/opportunities/runs",
            headers=headers,
            json=query.model_dump(mode="json") | {"max_pe": "100"},
        )
        assert bad.status_code == 409 and bad.json()["detail"]["code"] == "REQUEST_CONTENT_CONFLICT"
        bad = await client.post(
            "/api/v1/opportunities/facts",
            headers=headers,
            json=commands[0].model_dump(mode="json") | {"net_income": 20.5},
        )
        assert bad.status_code == 422


async def test_fact_and_funnel_snapshot_cannot_be_mutated_and_empty_scope_has_no_candidate(
    database_engine,
):
    from sqlalchemy.exc import DBAPIError

    sessions, store, service, commands, query = await setup(database_engine)
    receipt = await service.save_facts(commands[0])
    run = await service.run(query)
    async with sessions() as session:
        evidence = await session.get(EvidenceRecord, receipt.evidence_id)
        evidence.payload_json = {"changed": True}
        with pytest.raises(DBAPIError):
            await session.commit()
        await session.rollback()
        event = await session.scalar(
            select(EventLogRecord).where(
                EventLogRecord.aggregate_type == "opportunity_funnel_run",
                EventLogRecord.aggregate_id == run.run_id,
            )
        )
        event.payload_json = {"changed": True}
        with pytest.raises(DBAPIError):
            await session.commit()
        await session.rollback()
    assert await store.get_run(run.run_id) == run
    empty = await service.run(
        query.model_copy(update={"request_id": uuid4(), "instrument_ids": ()})
    )
    assert empty.status == "EMPTY" and empty.rows == () and empty.candidate_ids == ()


async def test_future_query_and_latest_future_facts_fail_closed_without_old_fact_fallback(
    database_engine,
):
    sessions, _, service, commands, query = await setup(database_engine)
    with pytest.raises(OpportunityError, match="FUTURE_AS_OF_NOT_ALLOWED"):
        await service.run(query.model_copy(update={"as_of": NOW + timedelta(seconds=1)}))
    assert await counts(sessions) == [0, 0, 0, 0, 0]
    await service.save_facts(commands[0])
    await service.save_facts(
        commands[0].model_copy(
            update={
                "request_id": uuid4(),
                "effective_at": NOW + timedelta(hours=1),
                "available_at": NOW + timedelta(hours=1),
                "expires_at": NOW + timedelta(hours=2),
            }
        )
    )
    run = await service.run(query)
    assert not run.candidate_ids
    assert "facts:NOT_YET_AVAILABLE" in run.rows[0].stages[0].missing_fields
    assert await counts(sessions) == [2, 2, 3, 3, 3]
