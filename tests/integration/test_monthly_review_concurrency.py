"""Real PostgreSQL transactions prove monthly local commit and authorization ordering."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_daily_scope_concurrency import audit
from test_monthly_review_pipeline import enable, setup

from investment_os.application.calendar_product import CalendarImportCommand, CalendarProductService
from investment_os.application.daily_runtime import DailyMode
from investment_os.application.monthly_review import MonthlyError
from investment_os.infrastructure.calendar_product import SqlCalendarProduct
from investment_os.infrastructure.manual_market_data import SqlManualMarketData
from investment_os.infrastructure.monthly_review_reader import SqlMonthlyReader
from investment_os.infrastructure.monthly_review_runner import MonthlyReviewRunner
from investment_os.infrastructure.monthly_review_store import SqlMonthlyReview
from investment_os.infrastructure.persistence.models import InstrumentRecord, PositionRecord

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
