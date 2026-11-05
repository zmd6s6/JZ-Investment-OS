"""Real PostgreSQL transactions prove monthly local commit and authorization ordering."""

import asyncio
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_daily_scope_concurrency import audit
from test_monthly_review_pipeline import enable, setup

from investment_os.api.app import create_app
from investment_os.application.calendar_product import CalendarImportCommand, CalendarProductService
from investment_os.application.daily_runtime import DailyMode
from investment_os.application.monthly_review import MonthlyError
from investment_os.infrastructure.calendar_product import SqlCalendarProduct
from investment_os.infrastructure.manual_market_data import SqlManualMarketData
from investment_os.infrastructure.monthly_review_models import MonthlyReportRecord
from investment_os.infrastructure.monthly_review_reader import SqlMonthlyReader
from investment_os.infrastructure.monthly_review_runner import MonthlyReviewRunner
from investment_os.infrastructure.monthly_review_store import SqlMonthlyReview, common
from investment_os.infrastructure.persistence.models import (
    InstrumentRecord,
    PositionRecord,
    TaskRunRecord,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("action", ["PAUSE", "REVOKE"])
async def test_monthly_pause_or_revoke_waits_real_held_transaction_then_prevents_late_commits(
    database_engine, action
):
    sessions, service, _, command, _ = await setup(database_engine)
    enabled = await enable(service, command)
    entered, release = asyncio.Event(), asyncio.Event()

    class HeldReader(SqlMonthlyReader):
        async def read(self, *args, **kwargs):
            entered.set()
            await release.wait()
            return await super().read(*args, **kwargs)

    runner = MonthlyReviewRunner(sessions, HeldReader(SqlManualMarketData(sessions)))
    writer_engine = create_async_engine(
        database_engine.url,
        connect_args={"server_settings": {"application_name": "monthly-mode-proof"}},
    )
    writer = SqlMonthlyReview(async_sessionmaker(writer_engine, expire_on_commit=False))
    running = asyncio.create_task(runner.dispatch_due(now=datetime.now(UTC)))
    pausing = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        pausing = asyncio.create_task(
            writer.mode(
                command.schedule_id,
                DailyMode(
                    request_id=uuid4(),
                    expected_version=enabled.version,
                    action=action,
                    confirmed=True,
                ),
            )
        )
        async with sessions() as observer, asyncio.timeout(5):
            while not await observer.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE application_name='monthly-mode-proof' "
                    "AND wait_event_type='Lock'"
                )
            ):
                if pausing.done():
                    await pausing  # Surface an early writer error instead of pretending it waited.
                await observer.execute(text("SELECT pg_stat_clear_snapshot()"))
                await asyncio.sleep(0.01)
        assert not pausing.done()
        release.set()
        await asyncio.wait_for(running, 15)
        await asyncio.wait_for(pausing, 15)
        assert len(await service.reports()) == 1
        assert await runner.dispatch_due(now=datetime.now(UTC)) == ()
        assert len(await service.reports()) == 1
    finally:
        release.set()
        for task in (running, pausing):
            if task and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (running, pausing) if task), return_exceptions=True)
        await writer_engine.dispose()


@pytest.mark.parametrize("action", ["PAUSE", "REVOKE"])
async def test_monthly_mode_confirmed_before_worker_means_no_report_or_new_task(
    database_engine, action
):
    _, service, runner, command, _ = await setup(database_engine)
    enabled = await enable(service, command)
    await service.mode(
        command.schedule_id,
        DailyMode(
            request_id=uuid4(), expected_version=enabled.version, action=action, confirmed=True
        ),
    )
    assert await runner.dispatch_due(now=datetime.now(UTC)) == ()
    assert await service.reports() == ()
    assert await service.runs() == ()


async def test_two_monthly_workers_have_one_real_business_report(database_engine):
    _, service, runner, command, _ = await setup(database_engine)
    await enable(service, command)
    await asyncio.gather(*(runner.dispatch_due(now=datetime.now(UTC)) for _ in range(2)))
    assert len(await service.reports()) == 1
    assert len(await service.runs()) == 1


@pytest.mark.parametrize("change", ["position", "calendar"])
@pytest.mark.parametrize("operation", ["SAVE", "ENABLE"])
@pytest.mark.parametrize("writer_first", [True, False])
async def test_monthly_save_enable_linearize_scope_and_calendar_changes(
    database_engine, monkeypatch, change, operation, writer_first
):
    import investment_os.infrastructure.monthly_review_store as module

    sessions, service, runner, command, _ = await setup(database_engine)
    prepared = await service.preview(command, datetime.now(UTC))
    saved = await service.save(command, prepared.content_hash) if operation == "ENABLE" else None
    writer_engine = create_async_engine(
        database_engine.url,
        connect_args={"server_settings": {"application_name": "monthly-scope-writer"}},
    )
    writer_sessions = async_sessionmaker(writer_engine, expire_on_commit=False)

    async def write():
        if change == "calendar":
            return await CalendarProductService(
                SqlCalendarProduct(writer_sessions)
            ).import_calendar(
                CalendarImportCommand(
                    request_id=uuid4(),
                    expected_version=1,
                    venue="SSE",
                    source_name="changed synthetic calendar",
                    source_version="v2",
                    confirmed_source=True,
                    csv_text=f"business_date,close_at\n{command.coverage_start},14:00\n{command.coverage_end},14:00\n",
                )
            )
        identifier = uuid4()
        async with writer_sessions() as session, session.begin():
            session.add(
                InstrumentRecord(
                    id=identifier,
                    symbol=f"M{str(identifier)[:10]}",
                    exchange="SSE",
                    asset_type="EQUITY",
                    currency="CNY",
                    **audit(),
                )
            )
            await session.flush()
            session.add(
                PositionRecord(
                    portfolio_id=command.portfolio_id, instrument_id=identifier, **audit()
                )
            )

    async def perform():
        if operation == "SAVE":
            return await service.save(command, prepared.content_hash)
        return await service.mode(
            command.schedule_id,
            DailyMode(
                request_id=uuid4(), expected_version=saved.version, action="ENABLE", confirmed=True
            ),
        )

    saving = writing = None
    entered, release = asyncio.Event(), asyncio.Event()
    try:
        if writer_first:
            await write()
            with pytest.raises(MonthlyError, match="MONTHLY_"):
                await perform()
        else:
            original = module.capture

            async def held_capture(*args, **kwargs):
                value = await original(*args, **kwargs)
                if kwargs.get("lock"):
                    entered.set()
                    await release.wait()
                return value

            monkeypatch.setattr(module, "capture", held_capture)
            saving = asyncio.create_task(perform())
            await asyncio.wait_for(entered.wait(), 5)
            writing = asyncio.create_task(write())
            async with sessions() as observer, asyncio.timeout(5):
                while not await observer.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE application_name='monthly-scope-writer' AND wait_event_type='Lock'"
                    )
                ):
                    if writing.done():
                        await writing
                    await observer.execute(text("SELECT pg_stat_clear_snapshot()"))
                    await asyncio.sleep(0.01)
            assert not writing.done()
            release.set()
            await asyncio.wait_for(saving, 10)
            await asyncio.wait_for(writing, 10)
            monkeypatch.setattr(module, "capture", original)
        assert await service.reports() == ()
        # A saved or enabled old snapshot cannot survive the committed identity/source change.
        if not writer_first and operation == "SAVE":
            config = (await service.configurations())[0]
            with pytest.raises(MonthlyError, match="MONTHLY_"):
                await service.mode(
                    command.schedule_id,
                    DailyMode(
                        request_id=uuid4(),
                        expected_version=config.version,
                        action="ENABLE",
                        confirmed=True,
                    ),
                )
        assert await runner.dispatch_due(now=datetime.now(UTC)) == ()
        assert await service.reports() == ()
    finally:
        release.set()
        for task in (saving, writing):
            if task and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (saving, writing) if task), return_exceptions=True)
        await writer_engine.dispose()


async def test_monthly_bounded_scan_survives_restarts_and_parallel_workers_and_pages_all_configs(
    database_engine,
):
    sessions, service, runner, command, _ = await setup(database_engine)
    today = datetime.now(UTC).date()
    year, month = today.year + today.month // 12, today.month % 12 + 1
    future_start = date(year, month, 1)
    future_end = date(year, month, monthrange(year, month)[1])
    # Real saved/enabled authorizations: 50 future periods preceding a completed one by UUID.
    for index in range(1, 52):
        update = {"schedule_id": UUID(int=index), "request_id": uuid4(), "name": f"合成{index}"}
        if index <= 50:
            update.update(coverage_start=future_start, coverage_end=future_end)
        candidate = command.model_copy(update=update)
        await enable(service, candidate)
    assert await runner.dispatch_due(now=datetime.now(UTC)) == ()
    async with sessions() as session:
        assert await session.scalar(
            text("SELECT after_id FROM monthly_scan_cursor WHERE id=1")
        ) == UUID(int=50)
    # Both are newly constructed Workers: the persisted cursor, not process memory,
    # makes 51 visible; serialized scanning + TaskRun uniqueness avoids duplicates.
    workers = [
        MonthlyReviewRunner(sessions, SqlMonthlyReader(SqlManualMarketData(sessions)))
        for _ in range(2)
    ]
    completed = await asyncio.gather(
        *(worker.dispatch_due(now=datetime.now(UTC)) for worker in workers)
    )
    assert sum(map(len, completed)) == 1
    assert len(await service.reports(UUID(int=51))) == 1
    assert len(await service.runs()) == 1
    for _ in range(3):
        await MonthlyReviewRunner(
            sessions, SqlMonthlyReader(SqlManualMarketData(sessions))
        ).dispatch_due(now=datetime.now(UTC))
    assert len(await service.reports(UUID(int=51))) == 1
    assert len(await service.runs()) == 1

    app = create_app(monthly_review_service=service, write_api_token="synthetic-monthly-only")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first, second = (
            await client.get("/api/v1/runtime/monthly"),
            await client.get("/api/v1/runtime/monthly?offset=50"),
        )
        assert first.status_code == second.status_code == 200
        assert len(first.json()) == 50 and len(second.json()) == 1
        assert len({item["schedule_id"] for item in first.json() + second.json()}) == 51
        assert (await client.get("/api/v1/runtime/monthly?offset=-1")).status_code == 422
    existing = next(
        item for item in await service.configurations() if item.schedule_id == UUID(int=51)
    )
    await service.mode(
        existing.schedule_id,
        DailyMode(
            request_id=uuid4(), expected_version=existing.version, action="REVOKE", confirmed=True
        ),
    )
    replacement = command.model_copy(update={"schedule_id": UUID(int=52), "request_id": uuid4()})
    saved = await service.save(
        replacement, (await service.preview(replacement, datetime.now(UTC))).content_hash
    )
    assert not saved.enabled
    all_configs = await service.configurations() + await service.configurations(offset=50)
    assert {config.schedule_id for config in all_configs} == {UUID(int=i) for i in range(1, 53)}
    assert next(config for config in all_configs if config.schedule_id == UUID(int=51)).revoked


async def test_monthly_report_history_and_task_api_pages_keep_older_rows_reachable(database_engine):
    sessions, service, runner, command, _ = await setup(database_engine)
    await enable(service, command)
    await runner.dispatch_due(now=datetime.now(UTC))
    now = datetime.now(UTC)
    async with sessions() as session, session.begin():
        original = await session.scalar(select(MonthlyReportRecord))
        assert original is not None
        for index in range(60):
            task_id = uuid4()
            session.add(
                TaskRunRecord(
                    id=task_id,
                    task_name="monthly_portfolio_review",
                    scheduled_for=now,
                    status="FAILED",
                    attempt=3,
                    idempotency_key=f"monthly:{command.schedule_id}:{uuid4()}:{index}",
                    input_hash="a" * 64,
                    started_at=now + timedelta(seconds=index),
                    finished_at=now,
                    error_json={"code": "SYNTHETIC_FAILURE"},
                    **common(uuid4()),
                )
            )
            await session.flush()
            values = {
                column.key: getattr(original, column.key)
                for column in MonthlyReportRecord.__table__.columns
            }
            values.update(
                id=uuid4(),
                task_run_id=task_id,
                period_start=date(2000, 1, 1) + timedelta(days=index),
                recorded_at=now + timedelta(seconds=index),
            )
            session.add(MonthlyReportRecord(**values))
        await session.flush()
    app = create_app(monthly_review_service=service, write_api_token="synthetic-monthly-only")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for path, key in (("history", "report_id"), ("runs", "task_run_id")):
            first = (await client.get(f"/api/v1/runtime/monthly/{path}")).json()
            second = (await client.get(f"/api/v1/runtime/monthly/{path}?offset=60")).json()
            assert len(first) == 60 and len(second) == 1
            assert len({row[key] for row in first + second}) == 61
            assert (
                await client.get(f"/api/v1/runtime/monthly/{path}?offset=-1")
            ).status_code == 422
        assert (await client.get("/api/v1/runtime/monthly/reports?offset=-1")).status_code == 422


async def test_monthly_scanner_cursor_recovers_after_interruption_before_job_start(
    database_engine, monkeypatch
):
    import investment_os.infrastructure.monthly_review_runner as module

    sessions, service, runner, command, _ = await setup(database_engine)
    await enable(service, command)
    original = module.ReliableJobExecutor.execute

    class Interrupted(BaseException):
        pass

    async def interrupted(*args, **kwargs):
        raise Interrupted()

    monkeypatch.setattr(module.ReliableJobExecutor, "execute", interrupted)
    with pytest.raises(Interrupted):
        await runner.dispatch_due(now=datetime.now(UTC))
    async with sessions() as session:
        assert (
            await session.scalar(text("SELECT after_id FROM monthly_scan_cursor WHERE id=1"))
            == command.schedule_id
        )
    assert await service.reports() == ()
    assert await service.runs() == ()
    monkeypatch.setattr(module.ReliableJobExecutor, "execute", original)
    resumed = MonthlyReviewRunner(sessions, SqlMonthlyReader(SqlManualMarketData(sessions)))
    assert len(await resumed.dispatch_due(now=datetime.now(UTC))) == 1
    assert len(await service.reports()) == 1
    assert len(await service.runs()) == 1
