"""Real SQL source intake, exact membership binding, atomicity and immutable history."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
import test_opportunity_funnel as fixture
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from investment_os.application.universe_snapshots import (
    UniverseConfirm,
    UniverseError,
    UniverseImport,
    UniverseRun,
    UniverseSnapshotService,
    UniverseSource,
)
from investment_os.infrastructure.persistence.models import (
    EventLogRecord,
    EvidenceRecord,
    InstrumentRecord,
    OutboxEventRecord,
    ResearchArtifactRecord,
)
from investment_os.infrastructure.universe_models import (
    UniverseMemberRecord,
    UniverseRunRecord,
    UniverseSnapshotRecord,
)
from investment_os.infrastructure.universe_snapshots import SqlUniverseSnapshots

pytestmark = pytest.mark.integration
NOW = fixture.NOW


async def setup(engine, count=2, *, facts=True):
    sessions, _, funnel, commands, query = await fixture.setup(engine, count)
    if facts:
        for command in commands:
            await funnel.save_facts(command)
    store = SqlUniverseSnapshots(sessions)
    service = UniverseSnapshotService(store, funnel, now=lambda: NOW)
    async with sessions() as session:
        records = (
            await session.scalars(select(InstrumentRecord).order_by(InstrumentRecord.symbol))
        ).all()
    source = UniverseSource(
        source_name="合成集合源",
        source_version="v1",
        source_locator="synthetic://members.csv",
        market="SSE",
        coverage_definition="明确声明的合成集合, 非市场全集",
        observed_at=NOW - timedelta(days=2),
        effective_at=NOW - timedelta(days=1),
        available_at=NOW - timedelta(hours=1),
        declared_total=count,
        completeness="DECLARED_COMPLETE",
    )
    command = UniverseImport(
        source=source, csv_text="market,symbol\n" + "\n".join("SSE," + r.symbol for r in records)
    )
    return sessions, store, service, command, query


async def confirm(service, command, request_id=None):
    preview = await service.preview(command)
    command = UniverseConfirm(
        **command.model_dump(),
        request_id=request_id or uuid4(),
        preview_hash=preview.preview_hash,
        legal_use_acknowledgement=True,
        declaration_acknowledgement=True,
    )
    return command, await service.confirm(command)


def run_command(snapshot, query):
    return UniverseRun(
        request_id=uuid4(),
        snapshot_hash=snapshot.content_hash,
        quote_source_name=query.quote_source_name,
        fact_source_name=query.fact_source_name,
        candidate_limit=query.candidate_limit,
        min_profit_margin=query.min_profit_margin,
        min_revenue_growth=query.min_revenue_growth,
        max_pe=query.max_pe,
        min_price_change=query.min_price_change,
    )


async def test_real_import_and_binding_keep_exact_members_provenance_and_unverified_coverage(
    database_engine,
):
    sessions, store, service, command, query = await setup(database_engine)
    confirmed, snapshot = await confirm(service, command)
    assert snapshot.member_count == 2 and snapshot.origin == "SOURCE_DECLARED"
    assert snapshot.verification == "UNVERIFIED" and snapshot.market_universe == "NOT_PROVIDED"
    assert snapshot.ingested_at == NOW and snapshot.evidence_id
    assert await service.confirm(confirmed) == snapshot
    assert await store.get(snapshot.snapshot_id) == snapshot
    assert (await store.list())[0].content_hash == snapshot.content_hash
    request = run_command(snapshot, query)
    bound = await service.run(snapshot.snapshot_id, request)
    assert set(bound.run.query.instrument_ids) == {m.instrument_id for m in snapshot.members}
    assert len(bound.run.rows) == 2 and len(bound.run.candidate_ids) == 1
    assert bound.origin.source.snapshot_id == snapshot.snapshot_id
    assert bound.run.market_universe == "NOT_PROVIDED" and not bound.run.auto_trade
    assert await service.run(snapshot.snapshot_id, request) == bound
    assert await store.origin(bound.run.run_id) == bound.origin
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(UniverseRunRecord)) == 1
        assert await session.scalar(select(func.count()).select_from(UniverseMemberRecord)) == 2
        # Membership evidence must never substitute for the quote/financial gate evidence.
        assert all(snapshot.evidence_id not in row.evidence_ids for row in bound.run.rows)


async def test_preview_drift_future_unknown_and_immutable_catalog_names_fail_closed(
    database_engine,
):
    sessions, store, service, command, query = await setup(database_engine)
    preview = await service.preview(command)
    request = UniverseConfirm(
        **command.model_dump(),
        request_id=uuid4(),
        preview_hash=preview.preview_hash,
        legal_use_acknowledgement=True,
        declaration_acknowledgement=True,
    )
    unknown = command.model_copy(update={"csv_text": "market,symbol\nSSE,UNKNOWN\nSSE,UNKNOWN2"})
    with pytest.raises(UniverseError, match="UNIVERSE_UNKNOWN_MEMBER"):
        await service.preview(unknown)
    future = command.model_copy(
        update={
            "source": command.source.model_copy(update={"available_at": NOW + timedelta(seconds=1)})
        }
    )
    with pytest.raises(UniverseError, match="UNIVERSE_FUTURE_SOURCE"):
        await service.preview(future)
    async with sessions() as session, session.begin():
        await session.execute(
            text("UPDATE instrument SET name='changed synthetic' WHERE id=:id"),
            {"id": preview.members[0].instrument_id},
        )
    with pytest.raises(UniverseError, match="UNIVERSE_PREVIEW_CONFLICT"):
        await service.confirm(request)
    _, snapshot = await confirm(service, command)
    async with sessions() as session, session.begin():
        await session.execute(
            text("UPDATE instrument SET name='newer synthetic' WHERE id=:id"),
            {"id": preview.members[0].instrument_id},
        )
    assert (await store.get(snapshot.snapshot_id)).members[0].name == "changed synthetic"
    too_early = run_command(snapshot, query).model_copy(
        update={"as_of": NOW - timedelta(microseconds=1)}
    )
    with pytest.raises(UniverseError, match="UNIVERSE_NOT_YET_AVAILABLE"):
        await service.run(snapshot.snapshot_id, too_early)


async def test_200_complete_members_run_and_201_refuses_without_truncation(database_engine):
    sessions, store, service, command, query = await setup(database_engine, facts=False)
    async with sessions() as session, session.begin():
        session.add_all(
            [
                InstrumentRecord(
                    id=uuid4(),
                    exchange="SSE",
                    symbol=f"SYN{n:06d}",
                    name="合成边界",
                    asset_type="EQUITY",
                    currency="CNY",
                    sector="Synthetic",
                    status="ACTIVE",
                    created_by="synthetic_fixture",
                    correlation_id=uuid4(),
                    metadata_json={},
                )
                for n in range(199)
            ]
        )
    async with sessions() as session:
        symbols = (
            await session.scalars(select(InstrumentRecord.symbol).order_by(InstrumentRecord.symbol))
        ).all()
    assert len(symbols) == 201
    large = command.model_copy(
        update={
            "source": command.source.model_copy(update={"declared_total": 201}),
            "csv_text": "market,symbol\n" + "\n".join("SSE," + s for s in symbols),
        }
    )
    preview = await service.preview(large)
    assert not preview.full_scan_supported and len(preview.members) == 201
    _, snapshot = await confirm(service, large)
    assert len((await store.get(snapshot.snapshot_id)).members) == 201
    with pytest.raises(UniverseError, match="UNIVERSE_SCAN_BOUND_EXCEEDED"):
        await service.run(snapshot.snapshot_id, run_command(snapshot, query))
    small = large.model_copy(
        update={
            "source": large.source.model_copy(update={"declared_total": 200}),
            "csv_text": "market,symbol\n" + "\n".join("SSE," + s for s in symbols[:200]),
        }
    )
    _, snapshot = await confirm(service, small)
    result = await service.run(snapshot.snapshot_id, run_command(snapshot, query))
    assert len(result.run.rows) == 200 and result.run.status == "DEGRADED"
    assert len(result.run.candidate_ids) == 0


@pytest.mark.parametrize("topic", ["universe.snapshot.imported", "universe.funnel.bound"])
async def test_outbox_fault_rolls_back_whole_import_or_bound_run_then_exact_retry(
    database_engine, topic
):
    sessions, _store, service, command, query = await setup(database_engine)
    preview = await service.preview(command)
    request = UniverseConfirm(
        **command.model_dump(),
        request_id=uuid4(),
        preview_hash=preview.preview_hash,
        legal_use_acknowledgement=True,
        declaration_acknowledgement=True,
    )
    snapshot = await service.confirm(request) if topic.endswith("bound") else None
    run = run_command(snapshot, query) if snapshot else None

    def fail(session, *_):
        if any(isinstance(row, OutboxEventRecord) and row.topic == topic for row in session.new):
            raise RuntimeError("synthetic outbox fault")

    event.listen(Session, "before_flush", fail)
    try:
        with pytest.raises(RuntimeError, match="synthetic outbox fault"):
            if run:
                await service.run(snapshot.snapshot_id, run)
            else:
                await service.confirm(request)
    finally:
        event.remove(Session, "before_flush", fail)
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(UniverseRunRecord)) == 0
        assert await session.scalar(select(func.count()).select_from(UniverseSnapshotRecord)) == (
            1 if snapshot else 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventLogRecord)
                .where(EventLogRecord.aggregate_type == "opportunity_funnel_run")
            )
            == 0
        )
        if not snapshot:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(EvidenceRecord)
                    .where(EvidenceRecord.metadata_json["provider"].astext == "MANUAL_UNIVERSE")
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ResearchArtifactRecord)
                    .where(ResearchArtifactRecord.provider == "MANUAL_UNIVERSE")
                )
                == 0
            )
    if run:
        await service.run(snapshot.snapshot_id, run)
    else:
        await service.confirm(request)


async def test_concurrent_import_deduplicates_receipts_and_evidence_without_changing_history(
    database_engine,
):
    sessions, _store, service, command, _ = await setup(database_engine)
    preview = await service.preview(command)
    request = UniverseConfirm(
        **command.model_dump(),
        request_id=uuid4(),
        preview_hash=preview.preview_hash,
        legal_use_acknowledgement=True,
        declaration_acknowledgement=True,
    )
    a, b = await asyncio.gather(service.confirm(request), service.confirm(request))
    assert a == b
    c = request.model_copy(update={"request_id": uuid4()})
    d = request.model_copy(update={"request_id": uuid4()})
    await asyncio.gather(service.confirm(c), service.confirm(d))
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(UniverseSnapshotRecord)) == 3
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EvidenceRecord)
                .where(EvidenceRecord.metadata_json["provider"].astext == "MANUAL_UNIVERSE")
            )
            == 1
        )
    with pytest.raises(UniverseError, match="REQUEST_CONTENT_CONFLICT"):
        await service.confirm(request.model_copy(update={"csv_text": request.csv_text + "\n"}))


async def test_append_only_origin_and_existing_manual_run_cannot_be_grafted(database_engine):
    sessions, store, service, command, query = await setup(database_engine)
    _, snapshot = await confirm(service, command)
    request = run_command(snapshot, query)
    existing_query = query.model_copy(
        update={
            "request_id": request.request_id,
            "scope_name": snapshot.source.source_name,
            "scope_locator": f"universe_snapshot:{snapshot.snapshot_id}:{snapshot.content_hash}",
            "instrument_ids": tuple(m.instrument_id for m in snapshot.members),
        }
    )
    original = await service.funnel.run(existing_query)
    with pytest.raises(UniverseError, match="REQUEST_CONTENT_CONFLICT"):
        await service.run(snapshot.snapshot_id, request)
    assert await store.origin(original.run_id) is None
    request = request.model_copy(update={"request_id": uuid4()})
    result = await service.run(snapshot.snapshot_id, request)
    for table in ("universe_snapshot", "universe_snapshot_member", "universe_funnel_origin"):
        async with sessions() as session:
            with pytest.raises(DBAPIError, match=r"append.only|immutable"):
                await session.execute(text(f"DELETE FROM {table}"))
            await session.rollback()
    assert (await store.origin(result.run.run_id)).source.content_hash == snapshot.content_hash


async def test_real_app_routes_require_auth_exact_confirmation_and_reject_forged_subsets(
    database_engine,
):
    from httpx import ASGITransport, AsyncClient

    from investment_os.api.app import create_app

    _, _, service, command, query = await setup(database_engine)
    app = create_app(universe_snapshot_service=service, write_api_token="synthetic-universe-only")
    headers = {"Authorization": "Bearer synthetic-universe-only"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (
            await client.post(
                "/api/v1/opportunities/universes/preview", json=command.model_dump(mode="json")
            )
        ).status_code == 401
        response = await client.post(
            "/api/v1/opportunities/universes/preview",
            headers=headers,
            json=command.model_dump(mode="json"),
        )
        assert response.status_code == 200
        confirm_input = {
            **command.model_dump(mode="json"),
            "request_id": str(uuid4()),
            "preview_hash": response.json()["preview_hash"],
            "legal_use_acknowledgement": True,
            "declaration_acknowledgement": True,
        }
        denied = await client.post(
            "/api/v1/opportunities/universes/imports",
            headers=headers,
            json={**confirm_input, "legal_use_acknowledgement": 1},
        )
        assert denied.status_code == 422
        receipt = await client.post(
            "/api/v1/opportunities/universes/imports", headers=headers, json=confirm_input
        )
        assert receipt.status_code == 200
        snapshot = receipt.json()
        run = {
            "request_id": str(uuid4()),
            "snapshot_hash": snapshot["content_hash"],
            "quote_source_name": query.quote_source_name,
            "fact_source_name": query.fact_source_name,
            "candidate_limit": 1,
            "min_profit_margin": "0.1",
            "min_revenue_growth": "0.1",
            "max_pe": "60",
            "min_price_change": "0",
        }
        path = "/api/v1/opportunities/universes/" + snapshot["snapshot_id"] + "/runs"
        assert (
            await client.post(path, headers=headers, json={**run, "instrument_ids": []})
        ).status_code == 422
        bound = await client.post(path, headers=headers, json=run)
        assert bound.status_code == 200 and len(bound.json()["run"]["rows"]) == 2
        origin = await client.get("/api/v1/opportunities/universes/origins/" + run["request_id"])
        assert origin.json()["source"]["snapshot_id"] == snapshot["snapshot_id"]
        assert (
            await client.get("/api/v1/opportunities/universes/origins/" + str(uuid4()))
        ).json() is None


async def test_migration_empty_roundtrip_preserves_business_and_history_refuses_downgrade(
    database_engine,
):
    from alembic import command as alembic_command
    from alembic.config import Config

    sessions, _, service, command, _ = await setup(database_engine)
    async with sessions() as session:
        before = await session.scalar(select(func.count()).select_from(EvidenceRecord))
    await database_engine.dispose()
    await asyncio.to_thread(alembic_command.downgrade, Config("alembic.ini"), "20261029_0019")
    await asyncio.to_thread(alembic_command.upgrade, Config("alembic.ini"), "head")
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(EvidenceRecord)) == before
    await confirm(service, command)
    await database_engine.dispose()
    with pytest.raises(DBAPIError, match="universe history exists"):
        await asyncio.to_thread(alembic_command.downgrade, Config("alembic.ini"), "20261029_0019")


async def test_production_weekly_rejects_members_imported_after_business_week(
    database_engine, monkeypatch
):
    import test_weekly_local_funnel as weekly

    from investment_os.application.opportunities import OpportunityError
    from investment_os.application.universe_snapshots import UniverseScopeNotYetAvailable
    from investment_os.infrastructure.weekly_funnel_models import WeeklyResultRecord
    from investment_os.worker.weekly_funnel import weekly_worker

    sessions, _, schedules, original, config, _ = await weekly.setup(database_engine, monkeypatch)
    runner = weekly_worker(sessions, now=lambda: weekly.MONDAY)
    source_service = UniverseSnapshotService(
        SqlUniverseSnapshots(sessions), runner.service, now=lambda: weekly.MONDAY
    )
    async with sessions() as session:
        records = (
            await session.scalars(select(InstrumentRecord).order_by(InstrumentRecord.symbol))
        ).all()
    draft = UniverseImport(
        source=UniverseSource(
            source_name="Synthetic late membership",
            source_version="v1",
            source_locator="synthetic://late.csv",
            market="SSE",
            coverage_definition="Finite synthetic list, not market universe",
            observed_at=weekly.FRIDAY,
            effective_at=weekly.FRIDAY,
            available_at=weekly.FRIDAY,
            declared_total=len(records),
            completeness="DECLARED_COMPLETE",
        ),
        csv_text="market,symbol\n" + "\n".join("SSE," + r.symbol for r in records),
    )
    _, snapshot = await confirm(source_service, draft)
    template = await SqlUniverseSnapshots(sessions).funnels.get_run(original.funnel_run_id)
    assert template is not None
    bound = await source_service.run(snapshot.snapshot_id, run_command(snapshot, template.query))
    with pytest.raises(UniverseScopeNotYetAvailable):
        await runner.service.prepare_run(
            bound.run.query.model_copy(update={"request_id": uuid4(), "as_of": weekly.FRIDAY})
        )
    with pytest.raises(OpportunityError, match="UNIVERSE_SCOPE_INVALID"):
        await runner.service.prepare_run(
            bound.run.query.model_copy(update={"request_id": uuid4(), "instrument_ids": (uuid4(),)})
        )
    with pytest.raises(OpportunityError, match="UNIVERSE_SCOPE_INVALID"):
        await runner.service.prepare_run(
            bound.run.query.model_copy(
                update={"request_id": uuid4(), "scope_locator": "universe_snapshot:invalid:hash"}
            )
        )
    config = await schedules.save(
        original.model_copy(
            update={
                "request_id": uuid4(),
                "expected_version": config.version,
                "funnel_run_id": bound.run.run_id,
            }
        )
    )
    await weekly.enable(schedules, config)
    await runner.dispatch_due(now=weekly.MONDAY)
    result = (await schedules.overview()).recent_runs[0]
    assert result.status == "FAILED"
    assert result.reason_code == "UniverseScopeNotYetAvailable"
    assert result.funnel_run_id is None
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(WeeklyResultRecord)) == 0
        assert await session.scalar(select(func.count()).select_from(UniverseRunRecord)) == 1
