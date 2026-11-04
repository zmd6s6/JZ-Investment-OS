"""Actual daily SQL authorization, worker report and immutable transaction lineage."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_daily_scope_concurrency import audit

from investment_os.application.calendar_product import CalendarImportCommand, CalendarProductService
from investment_os.application.daily_runtime import DailyMode, DailyRuntimeService, DailySave
from investment_os.infrastructure.analysis_runs import SqlAnalysisRuns
from investment_os.infrastructure.calendar_product import SqlCalendarProduct
from investment_os.infrastructure.daily_runtime_local import SqlDailyLocalReader
from investment_os.infrastructure.daily_runtime_models import (
    DailyExecutionRecord,
    DailyReportRecord,
)
from investment_os.infrastructure.daily_runtime_runner import DailyRuntimeRunner
from investment_os.infrastructure.daily_runtime_setup import SqlDailySetup
from investment_os.infrastructure.daily_runtime_store import SqlDailyRuntimeStore
from investment_os.infrastructure.manual_market_data import SqlManualMarketData
from investment_os.infrastructure.persistence.models import (
    InstrumentRecord,
    PortfolioRecord,
    PositionRecord,
)

pytestmark = pytest.mark.integration


async def setup(engine, monkeypatch):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    close = datetime.now(UTC).replace(second=0, microsecond=0)
    market_close = close.astimezone(ZoneInfo("Asia/Shanghai"))
    clock = {"now": close - timedelta(minutes=1)}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    monkeypatch.setattr("investment_os.infrastructure.daily_runtime_store.datetime", Clock)
    portfolio_id, instrument_id = uuid4(), uuid4()
    async with sessions() as session, session.begin():
        session.add(
            PortfolioRecord(id=portfolio_id, name="synthetic daily", base_currency="CNY", **audit())
        )
        session.add(
            InstrumentRecord(
                id=instrument_id,
                symbol="DAILY",
                exchange="SSE",
                asset_type="EQUITY",
                currency="CNY",
                **audit(),
            )
        )
        await session.flush()
        session.add(
            PositionRecord(portfolio_id=portfolio_id, instrument_id=instrument_id, **audit())
        )
    calendar = await CalendarProductService(SqlCalendarProduct(sessions)).import_calendar(
        CalendarImportCommand(
            request_id=uuid4(),
            expected_version=0,
            venue="SSE",
            source_name="Synthetic daily calendar",
            source_version="v1",
            confirmed_source=True,
            csv_text=f"business_date,close_at\n{market_close.date()},{market_close:%H:%M}\n",
        )
    )
    command = DailySave(
        request_id=uuid4(),
        schedule_id=uuid4(),
        expected_version=0,
        name="合成每日检查",
        mode="LOCAL_STATUS_ONLY",
        market="SSE",
        portfolio_id=portfolio_id,
        portfolio_instrument_ids=(instrument_id,),
        watchlist_instrument_ids=(),
        calendar_import_id=calendar.import_id,
        coverage_start=market_close.date(),
        coverage_end=market_close.date(),
        frequency="DAILY_AFTER_EXPLICIT_CLOSE",
        missed_run_policy="LOCAL_REPORT_ONLY_NO_RESEARCH",
        quote_source_name="Synthetic quote",
        evidence_source_names=(),
        retention_days=7,
        valid_from=close - timedelta(days=1),
        valid_until=close + timedelta(days=1),
        model_profiles={},
        data_profile_ids=(),
        limits=dict(currency="NONE", task_tokens=0, day_tokens=0, task_cost="0", day_cost="0"),
        pause_method="DAILY_UI_PAUSE_OR_REVOKE",
        complete_calendar_acknowledgement=True,
        scope_acknowledgement=True,
        local_only_acknowledgement=True,
        model_egress_acknowledgement=False,
        cost_acknowledgement=False,
    )
    prepared = SqlDailySetup(sessions, None, None)
    store = SqlDailyRuntimeStore(sessions, prepared)
    service = DailyRuntimeService(prepared, store)
    runner = DailyRuntimeRunner(
        sessions,
        SqlDailyLocalReader(SqlManualMarketData(sessions)),
        None,
        SqlAnalysisRuns(sessions),
    )
    return sessions, service, store, runner, command, close, clock


async def test_daily_local_save_enable_worker_report_is_atomic_idempotent_and_immutable(
    database_engine, monkeypatch
):
    sessions, service, store, runner, command, close, clock = await setup(
        database_engine, monkeypatch
    )
    saved = await service.save(command)
    assert not saved.enabled
    assert await service.save(command) == saved
    assert await runner.dispatch_due(now=close + timedelta(minutes=1)) == ()
    enabled = await store.mode(
        command.schedule_id,
        DailyMode(
            request_id=uuid4(), expected_version=saved.version, action="ENABLE", confirmed=True
        ),
    )
    assert enabled.enabled
    clock["now"] = close + timedelta(minutes=1)
    assert len(await runner.dispatch_due(now=clock["now"])) == 1
    assert await runner.dispatch_due(now=clock["now"]) == ()
    reports = await store.reports(command.schedule_id)
    assert len(reports) == 1
    report = reports[0]
    assert report.mode == "LOCAL_STATUS_ONLY" and report.auto_trade is False
    for field in (
        "action_required",
        "hold_watch",
        "new_opportunity",
        "risk_veto",
        "approvals",
        "data_job_degraded",
    ):
        assert getattr(report, field).messages
    assert report.approvals.availability == "NOT_PROVIDED"
    assert report.data_job_degraded.availability == "DEGRADED"
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(DailyExecutionRecord)) == 1
        assert await session.scalar(select(func.count()).select_from(DailyReportRecord)) == 1
    for table in (
        "daily_authorization_revision",
        "daily_authorized_member",
        "daily_report_revision",
        "daily_execution",
    ):
        with pytest.raises(DBAPIError, match=r"append-only|immutable"):
            async with database_engine.begin() as connection:
                await connection.execute(text(f"DELETE FROM {table}"))

    from alembic import command as migration_command
    from alembic.config import Config

    async with sessions() as session:
        original_revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
    with pytest.raises(RuntimeError, match="daily history exists"):
        await asyncio.to_thread(migration_command.downgrade, Config("alembic.ini"), "20261029_0021")
    async with sessions() as session:
        assert (
            await session.scalar(text("SELECT version_num FROM alembic_version"))
            == original_revision
        )
        assert await session.scalar(select(func.count()).select_from(DailyReportRecord)) == 1


async def test_daily_http_real_store_requires_write_auth_and_explicit_enable(
    database_engine, monkeypatch
):
    import httpx

    from investment_os.api.app import create_app

    _, service, _, _, command, _, _ = await setup(database_engine, monkeypatch)
    app = create_app(daily_runtime_service=service, write_api_token="synthetic-daily-token")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://local"
    ) as client:
        body = command.model_dump(mode="json")
        denied = await client.post("/api/v1/runtime/daily", json=body)
        assert denied.status_code == 401
        headers = {"Authorization": "Bearer synthetic-daily-token"}
        preview = await client.post("/api/v1/runtime/daily/preview", json=body, headers=headers)
        assert preview.status_code == 200, preview.text
        assert preview.json()["models"] == {}
        saved = await client.post("/api/v1/runtime/daily", json=body, headers=headers)
        assert saved.status_code == 200, saved.text
        assert saved.json()["enabled"] is False
        rejected = await client.post(
            f"/api/v1/runtime/daily/{command.schedule_id}/mode",
            headers=headers,
            json={
                "request_id": str(uuid4()),
                "expected_version": 1,
                "action": "ENABLE",
                "confirmed": False,
            },
        )
        assert rejected.status_code == 422
        overview = await client.get("/api/v1/runtime/daily")
        assert overview.status_code == 200 and len(overview.json()) == 1
        assert (await client.get("/api/v1/runtime/daily/reports")).json() == []


@pytest.mark.parametrize("pause_before_worker", ["NONE", "BEFORE", "DURING"])
async def test_daily_shadow_intent_reuses_real_analysis_with_per_call_authorization(
    database_engine, monkeypatch, pause_before_worker
):
    from test_analysis_numeric_pipeline import pipeline

    from investment_os.infrastructure.daily_runtime_fence import SqlDailyAuthorizationFence

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
    enabled = await store.mode(
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
        if pause_before_worker == "BEFORE":
            await store.mode(
                command.schedule_id,
                DailyMode(
                    request_id=uuid4(),
                    expected_version=enabled.version,
                    action="PAUSE",
                    confirmed=True,
                ),
            )
        if pause_before_worker == "DURING":
            running = asyncio.create_task(analysis_worker.dispatch_due())
            await asyncio.wait_for(entered.wait(), 5)
            from sqlalchemy.ext.asyncio import create_async_engine

            writer_engine = create_async_engine(
                database_engine.url,
                connect_args={"server_settings": {"application_name": "daily-pause-proof"}},
            )
            pause_store = SqlDailyRuntimeStore(
                async_sessionmaker(writer_engine, expire_on_commit=False), daily_setup
            )
            pausing = asyncio.create_task(
                pause_store.mode(
                    command.schedule_id,
                    DailyMode(
                        request_id=uuid4(),
                        expected_version=enabled.version,
                        action="PAUSE",
                        confirmed=True,
                    ),
                )
            )
            try:
                async with sessions() as observer, asyncio.timeout(5):
                    # Observe the real PostgreSQL writer wait, not only an unfinished Task.
                    while not await observer.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' "
                            "AND application_name='daily-pause-proof'"
                        )
                    ):
                        await asyncio.sleep(0.01)
                        await observer.execute(text("SELECT pg_stat_clear_snapshot()"))
                assert not pausing.done()
                release.set()
                await asyncio.wait_for(pausing, 15)
                calls_when_pause_confirmed = len(calls)
                await asyncio.wait_for(running, 15)
                assert len(calls) == calls_when_pause_confirmed
                assert calls
            finally:
                release.set()
                for task in (running, pausing):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(running, pausing, return_exceptions=True)
                await writer_engine.dispose()
        else:
            await analysis_worker.dispatch_due()
        await daily.refresh_reports(now=clock["now"])
        reports = await store.reports(command.schedule_id)
        assert len(reports) >= 2
        if pause_before_worker == "BEFORE":
            assert calls == []
            assert reports[0].phase == "DEGRADED"
        elif pause_before_worker == "NONE":
            assert len(calls) >= 9
            # Daily has no qualified numeric snapshot, so a completed shadow must
            # honestly retain the real analysis DEGRADED/UNKNOWN outcome.
            assert reports[0].phase == "DEGRADED"
            assert reports[0].hold_watch.analysis_run_ids
            run = await analyses.get(reports[0].hold_watch.analysis_run_ids[0])
            assert run.status.value == "DEGRADED"
            assert run.shadow_decision.risk_gate == "UNKNOWN"
        assert await daily.dispatch_due(now=clock["now"]) == ()
    finally:
        release.set()
        await client.aclose()


@pytest.mark.parametrize("writer_first", [False, True])
async def test_daily_save_scope_insert_linearizes_or_rejects_without_authorization_expansion(
    database_engine, monkeypatch, writer_first
):
    import asyncio

    from investment_os.application.daily_runtime import DailyError
    from investment_os.infrastructure.daily_runtime_models import DailyAuthorizationRecord

    sessions, service, store, _, command, _, _ = await setup(database_engine, monkeypatch)
    added_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            InstrumentRecord(
                id=added_id,
                symbol="EXTRA",
                exchange="SSE",
                asset_type="EQUITY",
                currency="CNY",
                **audit(),
            )
        )
    entered, release, writer_entered = asyncio.Event(), asyncio.Event(), asyncio.Event()
    pids = []

    async def verify(prepared, now):
        entered.set()
        await release.wait()

    async def writer():
        async with sessions() as session, session.begin():
            pids.append(await session.scalar(text("SELECT pg_backend_pid()")))
            writer_entered.set()
            session.add(
                PositionRecord(portfolio_id=command.portfolio_id, instrument_id=added_id, **audit())
            )
            await session.flush()

    if writer_first:
        await writer()
        with pytest.raises(DailyError, match="DAILY_PORTFOLIO_SCOPE_CHANGED"):
            await service.save(command)
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(DailyAuthorizationRecord))
                == 0
            )
        return
    monkeypatch.setattr(store.setup, "verify_profiles", verify)
    saving = asyncio.create_task(service.save(command))
    await asyncio.wait_for(entered.wait(), 3)
    writing = asyncio.create_task(writer())
    try:
        await asyncio.wait_for(writer_entered.wait(), 3)
        async with sessions() as observer:
            async with asyncio.timeout(3):
                # Observe PostgreSQL lock state; it cannot emit an asyncio Event.
                while (  # noqa: ASYNC110
                    await observer.scalar(
                        text("SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"),
                        {"pid": pids[0]},
                    )
                    != "Lock"
                ):
                    await asyncio.sleep(0.01)
        assert not writing.done()
        release.set()
        saved = await asyncio.wait_for(saving, 3)
        await asyncio.wait_for(writing, 3)
        with pytest.raises(DailyError, match="DAILY_PORTFOLIO_SCOPE_CHANGED"):
            await store.mode(
                command.schedule_id,
                DailyMode(
                    request_id=uuid4(),
                    expected_version=saved.version,
                    action="ENABLE",
                    confirmed=True,
                ),
            )
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(DailyAuthorizationRecord))
                == 1
            )
        assert not (await store.configurations())[0].enabled
    finally:
        release.set()
        for task in (saving, writing):
            if not task.done():
                task.cancel()
        await asyncio.gather(saving, writing, return_exceptions=True)


async def test_daily_revoke_is_terminal_in_real_postgresql_without_history_or_mode_writes(
    database_engine, monkeypatch
):
    from investment_os.application.daily_runtime import DailyError
    from investment_os.infrastructure.daily_runtime_models import DailyAuthorizationRecord
    from investment_os.infrastructure.persistence.models import EventLogRecord

    sessions, service, store, _, command, _, _ = await setup(database_engine, monkeypatch)
    saved = await service.save(command)
    revoke = DailyMode(
        request_id=uuid4(), expected_version=saved.version, action="REVOKE", confirmed=True
    )
    revoked = await store.mode(command.schedule_id, revoke)
    assert revoked.revoked and not revoked.enabled
    assert await store.mode(command.schedule_id, revoke) == revoked
    with pytest.raises(DailyError, match="DAILY_AUTHORIZATION_REVOKED"):
        await service.save(
            command.model_copy(update={"request_id": uuid4(), "expected_version": revoked.version})
        )
    for action in ("ENABLE", "PAUSE", "REVOKE"):
        with pytest.raises(DailyError, match="DAILY_AUTHORIZATION_REVOKED"):
            await store.mode(
                command.schedule_id,
                DailyMode(
                    request_id=uuid4(),
                    expected_version=revoked.version,
                    action=action,
                    confirmed=True,
                ),
            )
    with pytest.raises(DailyError, match="DAILY_VERSION_CONFLICT"):
        await store.mode(
            command.schedule_id,
            DailyMode(request_id=uuid4(), expected_version=1, action="ENABLE", confirmed=True),
        )
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(DailyAuthorizationRecord)) == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventLogRecord)
                .where(EventLogRecord.event_type == "daily.command")
            )
            == 2
        )
    actual = (await store.configurations())[0]
    assert actual.revoked and actual.version == revoked.version


@pytest.mark.parametrize("operation", ["SAVE", "ENABLE"])
@pytest.mark.parametrize("writer_first", [False, True])
async def test_daily_calendar_replacement_uses_real_row_lock_and_drift_block(
    database_engine, monkeypatch, operation, writer_first
):
    from sqlalchemy.ext.asyncio import create_async_engine

    from investment_os.application.daily_runtime import DailyError
    from investment_os.infrastructure.daily_runtime_models import DailyAuthorizationRecord

    sessions, service, store, _, command, close, _ = await setup(database_engine, monkeypatch)
    saved = await service.save(command) if operation == "ENABLE" else None
    entered, release = asyncio.Event(), asyncio.Event()
    writer_engine = create_async_engine(
        database_engine.url,
        connect_args={"server_settings": {"application_name": "daily-calendar-proof"}},
    )
    calendars = CalendarProductService(
        SqlCalendarProduct(async_sessionmaker(writer_engine, expire_on_commit=False))
    )
    market_close = close.astimezone(ZoneInfo("Asia/Shanghai"))
    replacement = CalendarImportCommand(
        request_id=uuid4(),
        expected_version=1,
        venue="SSE",
        source_name="Replacement synthetic calendar",
        source_version="v2",
        confirmed_source=True,
        csv_text=f"business_date,close_at\n{market_close.date()},{market_close:%H:%M}\n",
    )

    async def verify(prepared, now):
        entered.set()
        await release.wait()

    async def action():
        if operation == "SAVE":
            return await service.save(command)
        return await store.mode(
            command.schedule_id,
            DailyMode(
                request_id=uuid4(), expected_version=saved.version, action="ENABLE", confirmed=True
            ),
        )

    try:
        if writer_first:
            await calendars.import_calendar(replacement)
            with pytest.raises(DailyError, match="DAILY_CALENDAR_CHANGED_OR_MISSING"):
                await action()
        else:
            monkeypatch.setattr(store.setup, "verify_profiles", verify)
            acting = asyncio.create_task(action())
            await asyncio.wait_for(entered.wait(), 3)
            replacing = asyncio.create_task(calendars.import_calendar(replacement))
            try:
                async with sessions() as observer, asyncio.timeout(5):
                    while not await observer.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE application_name='daily-calendar-proof' "
                            "AND wait_event_type='Lock'"
                        )
                    ):
                        await asyncio.sleep(0.01)
                        await observer.execute(text("SELECT pg_stat_clear_snapshot()"))
                assert not replacing.done()
                release.set()
                actual = await asyncio.wait_for(acting, 5)
                await asyncio.wait_for(replacing, 5)
                if operation == "SAVE":
                    with pytest.raises(DailyError, match="DAILY_CALENDAR_CHANGED_OR_MISSING"):
                        await store.mode(
                            command.schedule_id,
                            DailyMode(
                                request_id=uuid4(),
                                expected_version=actual.version,
                                action="ENABLE",
                                confirmed=True,
                            ),
                        )
                else:
                    assert actual.enabled
                    assert (await store.configurations())[
                        0
                    ].blocker == "DAILY_CALENDAR_CHANGED_OR_MISSING"
            finally:
                release.set()
                for task in (acting, replacing):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(acting, replacing, return_exceptions=True)
        async with sessions() as session:
            expected = 1 if operation == "ENABLE" or not writer_first else 0
            assert (
                await session.scalar(select(func.count()).select_from(DailyAuthorizationRecord))
                == expected
            )
    finally:
        await writer_engine.dispose()


@pytest.mark.parametrize("offset_us", [-1, 0, 1])
async def test_daily_enable_rechecks_real_authorization_deadline_after_await(
    database_engine, monkeypatch, offset_us
):
    from investment_os.application.daily_runtime import DailyError
    from investment_os.infrastructure.persistence.models import EventLogRecord

    sessions, service, store, _, command, _, clock = await setup(database_engine, monkeypatch)
    saved = await service.save(command)
    entered, release = asyncio.Event(), asyncio.Event()
    original = store.setup.verify_profiles

    async def verify(prepared, now):
        await original(prepared, now)
        entered.set()
        await release.wait()

    monkeypatch.setattr(store.setup, "verify_profiles", verify)
    enabling = asyncio.create_task(
        store.mode(
            command.schedule_id,
            DailyMode(
                request_id=uuid4(), expected_version=saved.version, action="ENABLE", confirmed=True
            ),
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 3)
        clock["now"] = command.valid_until + timedelta(microseconds=offset_us)
        release.set()
        if offset_us < 0:
            assert (await asyncio.wait_for(enabling, 3)).enabled
        else:
            with pytest.raises(DailyError, match="DAILY_AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID"):
                await asyncio.wait_for(enabling, 3)
        async with sessions() as session:
            assert await session.scalar(
                select(func.count())
                .select_from(EventLogRecord)
                .where(EventLogRecord.event_type == "daily.command")
            ) == (2 if offset_us < 0 else 1)
    finally:
        release.set()
        if not enabling.done():
            enabling.cancel()
        await asyncio.gather(enabling, return_exceptions=True)
