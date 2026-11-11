"""Real PostgreSQL regressions for bounded traversal and reachable daily history."""

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import event, func, select, text
from test_daily_runtime_pipeline import setup

from investment_os.api.app import create_app
from investment_os.application.daily_runtime import DailyError, DailyMode
from investment_os.infrastructure.daily_runtime_models import (
    DailyExecutionRecord,
    DailyReportRecord,
)
from investment_os.infrastructure.daily_runtime_runner import DailyRuntimeRunner

pytestmark = pytest.mark.integration


async def populated(engine, monkeypatch, count):
    sessions, service, store, runner, command, close, clock = await setup(engine, monkeypatch)
    identifiers = []
    for index in range(count):
        identifier = UUID(int=index + 1)
        item = command.model_copy(
            update={"request_id": uuid4(), "schedule_id": identifier, "name": f"合成每日{index:03}"}
        )
        saved = await service.save(item)
        await store.mode(
            identifier,
            DailyMode(
                request_id=uuid4(), expected_version=saved.version, action="ENABLE", confirmed=True
            ),
        )
        identifiers.append(identifier)
    clock["now"] = close + timedelta(minutes=1)
    return sessions, service, store, runner, identifiers, clock


async def test_daily_106_configurations_reachable_across_restart_and_history_pages(
    database_engine, monkeypatch
):
    sessions, _, store, runner, ids, clock = await populated(database_engine, monkeypatch, 106)
    for index in range(15):
        # New runner instances exercise persisted progress across process lifetime boundaries.
        restarted = DailyRuntimeRunner(sessions, runner.local, runner.starter, runner.analyses)
        completed = await restarted.dispatch_due(now=clock["now"] + timedelta(seconds=index))
        assert len(completed) <= 8
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(DailyExecutionRecord)) == 106
        assert await session.scalar(select(func.count()).select_from(DailyReportRecord)) == 106
    assert len(await store.configurations()) == 50
    pages = [await store.configurations(offset=start) for start in (0, 50, 100)]
    assert {item.schedule_id for page in pages for item in page} == set(ids)
    assert len(await store.runs()) == 100
    assert len(await store.runs(offset=100)) == 6
    assert len(await store.report_history(offset=100)) == 6
    old = await store.configuration(ids[0])
    paused = await store.mode(
        ids[0],
        DailyMode(request_id=uuid4(), expected_version=old.version, action="PAUSE", confirmed=True),
    )
    assert not paused.enabled
    assert (await store.configuration(ids[0])).version == paused.version
    report = (await store.report_history(offset=100))[0]
    assert (await store.report(report.report_id)).report_id == report.report_id
    assert (await store.task(report.task_run_id)).task_run_id == report.task_run_id
    assert await runner.dispatch_due(now=clock["now"]) == ()


async def test_daily_concurrent_workers_traverse_tail_without_duplicate_business_effect(
    database_engine, monkeypatch
):
    sessions, _, _, runner, ids, clock = await populated(database_engine, monkeypatch, 51)
    for _ in range(5):
        results = await asyncio.gather(
            runner.dispatch_due(now=clock["now"]), runner.dispatch_due(now=clock["now"])
        )
        assert all(len(value) <= 8 for value in results)
    async with sessions() as session:
        executions = (await session.scalars(select(DailyExecutionRecord))).all()
        assert {item.schedule_id for item in executions} == set(ids)
        assert len(executions) == 51
        assert await session.scalar(select(func.count()).select_from(DailyReportRecord)) == 51


async def test_daily_old_pending_execution_is_eventually_finalized_and_original_hash_preserved(
    database_engine, monkeypatch
):
    from datetime import UTC, datetime

    from test_analysis_numeric_pipeline import pipeline

    from investment_os.application.daily_runtime import DailyRuntimeService, DailySave
    from investment_os.infrastructure.daily_runtime_fence import SqlDailyAuthorizationFence
    from investment_os.infrastructure.daily_runtime_local import SqlDailyLocalReader
    from investment_os.infrastructure.daily_runtime_setup import SqlDailySetup
    from investment_os.infrastructure.daily_runtime_store import SqlDailyRuntimeStore
    from investment_os.infrastructure.manual_market_data import SqlManualMarketData

    pause_before_worker = "NONE"
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold_first(wrapper):
        if pause_before_worker == "DURING" and not entered.is_set():
            entered.set()
            await release.wait()

    (
        sessions,
        starter,
        analyses,
        analysis_worker,
        analysis_command,
        calls,
        client,
        _,
    ) = await pipeline(database_engine, on_request=hold_first)
    _, _, _, _, local_command, close, clock = await setup(database_engine, monkeypatch)
    providers, budget = starter._providers, starter._budget
    profile = await providers.get_model_profile(
        next(iter(analysis_command.model_profiles.values()))
    )
    await providers.save_model_profile(
        profile_id=profile.id,
        credential=None,
        name=profile.name,
        provider_type=profile.provider_type,
        base_url=profile.base_url,
        model_name=profile.model_name,
        timeout_seconds=profile.timeout_seconds,
        max_tokens=profile.max_tokens,
        enabled=True,
        pricing_version=profile.pricing_version,
        pricing_currency=profile.pricing_currency,
        input_token_price=profile.input_token_price,
        output_token_price=profile.output_token_price,
        pricing_effective_at=close - timedelta(days=1),
    )
    command = DailySave.model_validate(
        {
            **local_command.model_dump(mode="json"),
            "mode": "SCHEDULED_SHADOW",
            "portfolio_id": str(analysis_command.portfolio_id),
            "portfolio_instrument_ids": [str(analysis_command.instrument_id)],
            "model_profiles": {
                role.value: str(value) for role, value in analysis_command.model_profiles.items()
            },
            "quote_source_name": analysis_command.market_source_name,
            "evidence_source_names": ["205明确合成数值来源"],
            "local_only_acknowledgement": False,
            "model_egress_acknowledgement": True,
            "cost_acknowledgement": True,
            "limits": dict(
                currency="CNY", task_tokens=2000000, day_tokens=4000000, task_cost="1", day_cost="2"
            ),
        }
    )
    daily_setup = SqlDailySetup(sessions, providers, budget)
    store = SqlDailyRuntimeStore(sessions, daily_setup)
    saved = await DailyRuntimeService(daily_setup, store).save(command)
    await store.mode(
        command.schedule_id,
        DailyMode(
            request_id=uuid4(), expected_version=saved.version, action="ENABLE", confirmed=True
        ),
    )
    clock["now"] = datetime.now(UTC)
    daily = DailyRuntimeRunner(
        sessions, SqlDailyLocalReader(SqlManualMarketData(sessions)), starter, analyses
    )
    fence = SqlDailyAuthorizationFence(sessions, daily_setup, now=lambda: clock["now"])
    execution = analysis_worker._orchestrator._execution
    execution._preparer._runtime_authorization = fence
    execution._gateways._runtime_authorization = fence
    try:
        assert len(await daily.dispatch_due(now=clock["now"])) == 1
        prior = (await store.reports(command.schedule_id))[0]
        assert prior.phase == "SHADOW_PENDING"
        async with sessions() as session:
            original_hash = (await session.get(DailyReportRecord, prior.report_id)).content_hash
        clock["now"] = close - timedelta(minutes=1)
        for index in range(51):
            local = local_command.model_copy(
                update={"request_id": uuid4(), "schedule_id": UUID(int=index + 2)}
            )
            saved = await DailyRuntimeService(daily_setup, store).save(local)
            await store.mode(
                local.schedule_id,
                DailyMode(
                    request_id=uuid4(),
                    expected_version=saved.version,
                    action="ENABLE",
                    confirmed=True,
                ),
            )
        clock["now"] = datetime.now(UTC) + timedelta(seconds=1)
        for index in range(7):
            await daily.dispatch_due(now=clock["now"] + timedelta(seconds=index))
        from investment_os.infrastructure.daily_runtime_store import common

        # Explicit corrupt synthetic history must not pin any bounded batch before
        # the one valid, older pending execution. Original rows remain immutable.
        async with sessions() as session, session.begin():
            local_reports = (
                await session.scalars(
                    select(DailyReportRecord)
                    .join(
                        DailyExecutionRecord,
                        DailyReportRecord.execution_id == DailyExecutionRecord.id,
                    )
                    .where(DailyExecutionRecord.schedule_id != command.schedule_id)
                )
            ).all()
            for local_report in local_reports:
                session.add(
                    DailyReportRecord(
                        id=uuid4(),
                        execution_id=local_report.execution_id,
                        sequence=local_report.sequence + 1,
                        phase=local_report.phase,
                        recorded_at=clock["now"] + timedelta(seconds=8),
                        usable_until=local_report.usable_until,
                        report_json=local_report.report_json,
                        content_hash="0" * 64,
                        **common(uuid4()),
                    )
                )
        await analysis_worker.dispatch_due()
        for _ in range(3):
            await daily.refresh_reports(now=clock["now"] + timedelta(seconds=30))
        reports = await store.reports(command.schedule_id)
        assert len(reports) >= 2 and reports[0].phase != "SHADOW_PENDING"
        for _ in range(3):
            await daily.refresh_reports(now=clock["now"] + timedelta(seconds=31))
        assert len(await store.reports(command.schedule_id)) == len(reports)
        assert len(calls) >= 9
        history = await store.report_history()
        assert sum(item.availability == "INVALID" for item in history) == 51
        async with sessions() as session:
            assert (
                await session.get(DailyReportRecord, prior.report_id)
            ).content_hash == original_hash
    finally:
        await client.aclose()


async def test_daily_exact_reads_pagination_expiry_and_missing_record_fail_closed(
    database_engine, monkeypatch
):
    _, service, store, runner, ids, clock = await populated(database_engine, monkeypatch, 1)
    await runner.dispatch_due(now=clock["now"])
    audit = (await store.report_history())[0]
    writes = []

    def watch(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(database_engine.sync_engine, "before_cursor_execute", watch)
    try:
        app = create_app(daily_runtime_service=service)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            for route in (
                f"/configurations/{ids[0]}",
                f"/runs/{audit.task_run_id}",
                f"/reports/{audit.report_id}",
                "/history?offset=0&limit=1",
            ):
                assert (await client.get("/api/v1/runtime/daily" + route)).status_code == 200
            for route in ("?offset=-1", "/history?limit=101", "/runs?limit=0"):
                assert (await client.get("/api/v1/runtime/daily" + route)).status_code == 422
            assert (await client.get(f"/api/v1/runtime/daily/reports/{uuid4()}")).status_code == 404
        clock["now"] = audit.usable_until
        assert (await store.report_history())[0].availability == "EXPIRED"
        assert await store.reports() == ()
        with pytest.raises(DailyError, match="EXPIRED_HISTORY_PRESERVED"):
            await store.report(audit.report_id)
        assert not writes
    finally:
        event.remove(database_engine.sync_engine, "before_cursor_execute", watch)


async def test_daily_cursor_migration_is_reconstructible_without_business_history_loss(
    database_engine,
):
    async with database_engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO daily_scan_cursor VALUES ('CONFIGURATION', NULL)")
        )
        assert await connection.scalar(text("SELECT count(*) FROM daily_scan_cursor")) == 1
