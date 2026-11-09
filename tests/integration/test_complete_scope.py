"""Complete declared-snapshot scans against the real transactional PostgreSQL store."""

import asyncio
from uuid import uuid4

import pytest
import test_universe_snapshots as fixture
from sqlalchemy import func, select

from investment_os.application.complete_scope import CompleteScopeCommand, CompleteScopeService
from investment_os.application.universe_snapshots import UniverseError, UniverseRun
from investment_os.infrastructure.complete_scope import SqlCompleteScope
from investment_os.infrastructure.persistence.models import InstrumentRecord, OutboxEventRecord
from investment_os.infrastructure.universe_models import UniverseRunRecord

pytestmark = pytest.mark.integration


async def prepare(engine, count, qualified=2):
    sessions, _store, old_service, command, query = await fixture.setup(
        engine, count=qualified, facts=True
    )
    async with sessions() as session, session.begin():
        session.add_all(
            [
                InstrumentRecord(
                    id=uuid4(),
                    exchange="SSE",
                    symbol=f"SYN{n:06d}",
                    name="合成标的",
                    asset_type="EQUITY",
                    currency="CNY",
                    sector="Synthetic",
                    status="ACTIVE",
                    created_by="synthetic_fixture",
                    correlation_id=uuid4(),
                    metadata_json={},
                )
                for n in range(count - qualified)
            ]
        )
    async with sessions() as session:
        symbols = (
            await session.scalars(select(InstrumentRecord.symbol).order_by(InstrumentRecord.symbol))
        ).all()
    command = command.model_copy(
        update={
            "source": command.source.model_copy(update={"declared_total": count}),
            "csv_text": "market,symbol\n" + "\n".join("SSE," + s for s in symbols),
        }
    )
    _, snapshot = await fixture.confirm(old_service, command)
    request = CompleteScopeCommand(**fixture.run_command(snapshot, query).model_dump())
    store = SqlCompleteScope(sessions)
    return (
        sessions,
        old_service,
        snapshot,
        request,
        store,
        CompleteScopeService(store, old_service.funnel, now=lambda: fixture.NOW),
    )


@pytest.mark.parametrize("count", [201, 1000])
async def test_whole_declared_scope_no_truncation_and_replay(database_engine, count):
    sessions, old, snapshot, command, store, service = await prepare(database_engine, count)
    with pytest.raises(UniverseError, match="UNIVERSE_SCAN_BOUND_EXCEEDED"):
        await old.run(
            snapshot.snapshot_id,
            UniverseRun.model_validate(command.model_dump(exclude={"protocol_version"})),
        )
    result = await service.run(snapshot.snapshot_id, command)
    assert len(result.rows) == count
    assert {r.instrument_id for r in result.rows} == {m.instrument_id for m in snapshot.members}
    assert result.source.origin == "SOURCE_DECLARED" and result.source.verification == "UNVERIFIED"
    assert result.market_universe == "NOT_PROVIDED" and result.model_calls == 0
    assert result.external_calls == result.paid_calls == 0 and result.auto_trade is False
    assert len(result.candidate_ids) == 1
    assert await service.run(snapshot.snapshot_id, command) == result
    assert await store.get_complete(command.request_id) == result
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(UniverseRunRecord)) == 1
    with pytest.raises(UniverseError, match="REQUEST_CONTENT_CONFLICT"):
        await service.run(snapshot.snapshot_id, command.model_copy(update={"max_pe": "70"}))


async def test_outbox_failure_rolls_back_and_retry_is_idempotent(database_engine, monkeypatch):
    sessions, _old, snapshot, command, _store, service = await prepare(database_engine, 2)
    from investment_os.infrastructure.persistence.repositories import OutboxRepository

    original = OutboxRepository.add

    async def fail(self, value):
        if value.topic == "universe.complete_scope.bound":
            raise RuntimeError("synthetic outbox failure")
        return await original(self, value)

    monkeypatch.setattr(OutboxRepository, "add", fail)
    with pytest.raises(RuntimeError, match="synthetic outbox"):
        await service.run(snapshot.snapshot_id, command)
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(UniverseRunRecord)) == 0
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OutboxEventRecord)
                .where(OutboxEventRecord.topic == "universe.complete_scope.bound")
            )
            == 0
        )
    monkeypatch.setattr(OutboxRepository, "add", original)
    first, second = await asyncio.gather(
        service.run(snapshot.snapshot_id, command), service.run(snapshot.snapshot_id, command)
    )
    assert first == second
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(UniverseRunRecord)) == 1


async def test_api_v2_roundtrip_and_legacy_request_identity_collision(database_engine):
    from httpx import ASGITransport, AsyncClient

    from investment_os.api.app import create_app
    from investment_os.application.opportunities import FunnelQuery, OpportunityError

    _sessions, old, snapshot, command, store, service = await prepare(database_engine, 2)
    app = create_app(
        universe_snapshot_service=old,
        complete_scope_service=service,
        write_api_token="synthetic-v2",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = command.model_dump(mode="json")
        rejected = await client.post(
            f"/api/v1/opportunities/universes/{snapshot.snapshot_id}/complete-runs", json=body
        )
        assert rejected.status_code == 401
        response = await client.post(
            f"/api/v1/opportunities/universes/{snapshot.snapshot_id}/complete-runs",
            json=body,
            headers={"Authorization": "Bearer synthetic-v2"},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["schema_version"] == "2.0" and len(result["rows"]) == 2
        assert result["source"]["verification"] == "UNVERIFIED"
        history = await client.get("/api/v1/opportunities/universes/complete-runs")
        assert history.status_code == 200 and history.json()[0]["run_id"] == str(command.request_id)
        detail = await client.get(
            f"/api/v1/opportunities/universes/complete-runs/{command.request_id}"
        )
        assert detail.status_code == 200 and detail.json() == result
    legacy = FunnelQuery(
        request_id=command.request_id,
        instrument_ids=(),
        scope_name="synthetic",
        scope_locator="synthetic://manual",
        quote_source_name=command.quote_source_name,
        fact_source_name=command.fact_source_name,
        as_of=fixture.NOW,
        candidate_limit=command.candidate_limit,
        min_profit_margin=command.min_profit_margin,
        min_revenue_growth=command.min_revenue_growth,
        max_pe=command.max_pe,
        min_price_change=command.min_price_change,
    )
    with pytest.raises(OpportunityError, match="REQUEST_CONTENT_CONFLICT"):
        await old.funnel.run(legacy)
    assert await store.get_complete(command.request_id) is not None


async def test_identity_drift_and_invalid_time_leave_no_partial_run(database_engine):
    from datetime import timedelta

    from sqlalchemy import text

    from investment_os.application.opportunities import OpportunityError

    sessions, _old, snapshot, command, _store, service = await prepare(database_engine, 2)
    with pytest.raises(UniverseError, match="UNIVERSE_NOT_YET_AVAILABLE"):
        await service.run(
            snapshot.snapshot_id,
            command.model_copy(update={"as_of": fixture.NOW - timedelta(microseconds=1)}),
        )
    with pytest.raises(OpportunityError, match="FUTURE_AS_OF_NOT_ALLOWED"):
        await service.run(
            snapshot.snapshot_id,
            command.model_copy(update={"as_of": fixture.NOW + timedelta(microseconds=1)}),
        )
    with pytest.raises(UniverseError, match="UNIVERSE_SNAPSHOT_CONFLICT"):
        await service.run(
            snapshot.snapshot_id, command.model_copy(update={"snapshot_hash": "f" * 64})
        )
    async with sessions() as session, session.begin():
        await session.execute(
            text("UPDATE instrument SET name='drifted synthetic' WHERE id=:id"),
            {"id": snapshot.members[0].instrument_id},
        )
    with pytest.raises(UniverseError, match="UNIVERSE_IDENTITY_MISMATCH"):
        await service.run(snapshot.snapshot_id, command)
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(UniverseRunRecord)) == 0


async def test_201_member_global_order_selects_twenty_of_25_qualified(database_engine):
    _sessions, _old, snapshot, command, _store, service = await prepare(database_engine, 201, 25)
    result = await service.run(
        snapshot.snapshot_id, command.model_copy(update={"candidate_limit": 20})
    )
    qualified = [row for row in result.rows if row.stages[-1].stage == "BOUND"]
    assert len(qualified) == 25 and len(result.candidate_ids) == 20
    assert result.candidate_ids == tuple(row.instrument_id for row in qualified[:20])
    assert all(row.stages[-1].reason == "CANDIDATE_LIMIT_REACHED" for row in qualified[20:])
    assert all(snapshot.evidence_id not in row.evidence_ids for row in result.rows)
