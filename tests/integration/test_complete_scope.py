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


async def prepare(engine, count):
    sessions, _store, old_service, command, query = await fixture.setup(engine, facts=True)
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
                for n in range(count - 2)
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
