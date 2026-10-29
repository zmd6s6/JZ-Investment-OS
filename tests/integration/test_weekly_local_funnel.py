"""Real local weekly task/produce/outbox atomicity, exact scope and pause races."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
import test_opportunity_funnel as fixture
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from investment_os.application.calendar_product import CalendarImportCommand, CalendarProductService
from investment_os.application.opportunities import OpportunityError
from investment_os.application.opportunity_schedule import WeeklyMode, WeeklySave
from investment_os.infrastructure.calendar_product import SqlCalendarProduct
from investment_os.infrastructure.opportunity_schedule import SqlWeeklyFunnel, WeeklyFunnelRunner
from investment_os.infrastructure.persistence.jobs import ReliableJobExecutor
from investment_os.infrastructure.persistence.models import (
    EventLogRecord,
    OutboxEventRecord,
    TaskRunRecord,
)
from investment_os.infrastructure.weekly_funnel_models import WeeklyResultRecord

pytestmark = pytest.mark.integration
FRIDAY = datetime(2026, 10, 23, 7, tzinfo=UTC)
MONDAY = datetime(2026, 10, 26, tzinfo=UTC)


async def setup(database_engine, monkeypatch, *, closed=False, expired=False):
    monkeypatch.setattr(fixture, "NOW", FRIDAY)
    sessions, _, service, facts, query = await fixture.setup(database_engine)
    for fact in facts:
        await service.save_facts(
            fact.model_copy(update={"expires_at": FRIDAY - timedelta(minutes=1)})
            if expired
            else fact
        )
    funnel = await service.run(query)
    calendars = CalendarProductService(SqlCalendarProduct(sessions))
    calendar = await calendars.import_calendar(
        CalendarImportCommand(
            request_id=uuid4(),
            expected_version=0,
            venue="SSE",
            source_name="Synthetic explicit whole calendar",
            source_version="v1",
            csv_text="business_date,close_at\n2026-10-16,15:00\n2026-10-30,15:00\n"
            if closed
            else "business_date,close_at\n2026-10-23,15:00\n2026-10-26,15:00\n",
            confirmed_source=True,
        )
    )
    store = SqlWeeklyFunnel(sessions)
    command = WeeklySave(
        request_id=uuid4(),
        schedule_id=uuid4(),
        expected_version=0,
        name="Synthetic weekly",
        venue="SSE",
        funnel_run_id=funnel.run_id,
        calendar_import_id=calendar.import_id,
        coverage_start=date(2026, 10, 19),
        coverage_end=date(2026, 10, 25),
        complete_calendar_acknowledgement=True,
        local_only_acknowledgement=True,
    )
    config = await store.save(command)
    return sessions, service, store, command, config, calendars


async def enable(store, config, enabled=True):
    return await store.mode(
        config.schedule_id,
        WeeklyMode(
            request_id=uuid4(),
            expected_version=config.version,
            enabled=enabled,
            local_only_acknowledgement=True,
        ),
    )


async def test_real_weekly_default_paused_atomic_result_and_concurrent_replay(
    database_engine, monkeypatch
):
    sessions, service, store, command, config, _ = await setup(database_engine, monkeypatch)
    runner = WeeklyFunnelRunner(sessions, service)
    assert not config.enabled and config.blocker == "WEEKLY_PAUSED"
    assert await runner.dispatch_due(now=MONDAY) == ()
    assert await store.save(command) == config
    config = await enable(store, config)
    assert await runner.dispatch_due(now=FRIDAY) == ()  # Full natural week has not ended.
    await asyncio.gather(*[runner.dispatch_due(now=MONDAY) for _ in range(3)])
    overview = await store.overview()
    assert len(overview.recent_runs) == 1
    run = overview.recent_runs[0]
    assert run.status == "COMPLETE" and run.candidate_count == 1 and run.as_of == FRIDAY
    assert run.funnel_run_id != command.funnel_run_id
    assert await runner.dispatch_due(now=MONDAY) == ()
    async with sessions() as session:
        receipt = await session.scalar(
            select(EventLogRecord).where(
                EventLogRecord.event_type == "weekly.command",
                EventLogRecord.aggregate_id == command.request_id,
            )
        )
        assert receipt is not None
        assert receipt.payload_json["command"]["complete_calendar_acknowledgement"] is True
        assert receipt.payload_json["command"]["local_only_acknowledgement"] is True
        assert await session.scalar(select(func.count()).select_from(WeeklyResultRecord)) == 1
        assert await session.scalar(select(func.count()).select_from(TaskRunRecord)) == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventLogRecord)
                .where(EventLogRecord.event_type == "weekly.completed")
            )
            == 1
        )
    paused = await enable(store, config, False)
    await enable(store, paused)
    assert await runner.dispatch_due(now=MONDAY) == ()


async def test_declared_closed_week_gets_explicit_skip_without_funnel(database_engine, monkeypatch):
    sessions, service, store, _, config, _ = await setup(database_engine, monkeypatch, closed=True)
    await enable(store, config)
    await WeeklyFunnelRunner(sessions, service).dispatch_due(now=MONDAY)
    result = (await store.overview()).recent_runs[0]
    assert result.status == "SKIPPED_CLOSED" and result.reason_code == "MARKET_CLOSED"
    assert result.funnel_run_id is None and result.candidate_count is None


async def test_outbox_fault_rolls_back_funnel_result_then_retry_is_unique(
    database_engine, monkeypatch
):
    sessions, service, store, _, config, _ = await setup(database_engine, monkeypatch)
    await enable(store, config)
    runner = WeeklyFunnelRunner(sessions, service)

    def reject(session, _ctx, _instances):
        if any(
            isinstance(row, OutboxEventRecord) and row.topic == "weekly.completed"
            for row in session.new
        ):
            raise RuntimeError("synthetic outbox fault")

    event.listen(Session, "before_flush", reject)
    try:
        await runner.dispatch_due(now=MONDAY)
    finally:
        event.remove(Session, "before_flush", reject)
    history = await store.overview()
    assert history.recent_runs[0].status == "FAILED"
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(WeeklyResultRecord)) == 0
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventLogRecord)
                .where(EventLogRecord.aggregate_type == "opportunity_funnel_run")
            )
            == 1
        )  # Only original template.
    await runner.dispatch_due(now=MONDAY)
    history = await store.overview()
    assert len(history.recent_runs) == 1 and history.recent_runs[0].attempt == 2
    assert history.recent_runs[0].status == "COMPLETE"


async def test_pause_wins_after_plan_no_stale_result_then_resume_recovers(
    database_engine, monkeypatch
):
    sessions, service, store, _, config, _ = await setup(database_engine, monkeypatch)
    config = await enable(store, config)
    entered, release = asyncio.Event(), asyncio.Event()
    original = ReliableJobExecutor.execute

    async def wait(self, **kwargs):
        entered.set()
        await release.wait()
        return await original(self, **kwargs)

    monkeypatch.setattr(ReliableJobExecutor, "execute", wait)
    runner = WeeklyFunnelRunner(sessions, service)
    task = asyncio.create_task(runner.dispatch_due(now=MONDAY))
    await asyncio.wait_for(entered.wait(), 2)
    paused = await enable(store, config, False)
    release.set()
    await task
    assert (await store.overview()).recent_runs[0].status == "FAILED"
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(WeeklyResultRecord)) == 0
    monkeypatch.setattr(ReliableJobExecutor, "execute", original)
    await enable(store, paused)
    await runner.dispatch_due(now=MONDAY)
    assert (await store.overview()).recent_runs[0].status == "COMPLETE"


async def test_calendar_source_change_blocks_no_silent_rebinding_and_new_revision_paused(
    database_engine, monkeypatch
):
    sessions, service, store, command, config, calendars = await setup(database_engine, monkeypatch)
    config = await enable(store, config)
    replacement = await calendars.import_calendar(
        CalendarImportCommand(
            request_id=uuid4(),
            expected_version=1,
            venue="SSE",
            source_name="new synthetic calendar",
            source_version="v2",
            csv_text="business_date,close_at\n2026-10-23,15:00\n",
            confirmed_source=True,
        )
    )
    assert (await store.overview()).configurations[
        0
    ].blocker == "WEEKLY_CALENDAR_CHANGED_OR_MISSING"
    assert await WeeklyFunnelRunner(sessions, service).dispatch_due(now=MONDAY) == ()
    changed = command.model_copy(
        update={
            "request_id": uuid4(),
            "expected_version": config.version,
            "calendar_import_id": replacement.import_id,
        }
    )
    new = await store.save(changed)
    assert new.revision_id != config.revision_id and not new.enabled
    with pytest.raises(OpportunityError, match="WEEKLY_VERSION_CONFLICT"):
        await enable(store, config)


async def test_handler_wins_pause_waits_for_atomic_commit_then_no_late_side_effects(
    database_engine, monkeypatch
):
    sessions, service, store, _, config, _ = await setup(database_engine, monkeypatch)
    config = await enable(store, config)
    entered, release = asyncio.Event(), asyncio.Event()
    original = service.prepare_run

    async def held(query):
        entered.set()
        await release.wait()
        return await original(query)

    monkeypatch.setattr(service, "prepare_run", held)
    runner = WeeklyFunnelRunner(sessions, service)
    task = asyncio.create_task(runner.dispatch_due(now=MONDAY))
    await asyncio.wait_for(entered.wait(), 2)
    pause = asyncio.create_task(enable(store, config, False))
    done, _ = await asyncio.wait({pause}, timeout=0.1)
    assert not done  # Pause acknowledgement must wait while the gate owns the config row.
    release.set()
    await asyncio.wait_for(asyncio.gather(task, pause), 3)
    assert (await store.overview()).recent_runs[0].status == "COMPLETE"
    assert not (await store.overview()).configurations[0].enabled
    assert await runner.dispatch_due(now=MONDAY) == ()
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(WeeklyResultRecord)) == 1


async def test_expired_facts_are_degraded_without_paid_or_research_fallback(
    database_engine, monkeypatch
):
    sessions, service, store, _, config, _ = await setup(database_engine, monkeypatch, expired=True)
    await enable(store, config)
    await WeeklyFunnelRunner(sessions, service).dispatch_due(now=MONDAY)
    run = (await store.overview()).recent_runs[0]
    assert run.status == "DEGRADED" and run.reason_code == "LOCAL_DATA_MISSING"
    assert run.candidate_count == 0
    assert (await store.overview()).configurations[0].paid_calls == 0


async def test_weekly_revision_members_and_result_are_append_only_and_downgrade_refuses_history(
    database_engine, monkeypatch
):
    from alembic import command as alembic_command
    from alembic.config import Config

    sessions, service, store, _, config, _ = await setup(database_engine, monkeypatch)
    await enable(store, config)
    await WeeklyFunnelRunner(sessions, service).dispatch_due(now=MONDAY)
    for table in ("weekly_funnel_revision", "weekly_funnel_member", "weekly_funnel_result"):
        async with sessions() as session:
            with pytest.raises(
                DBAPIError,
                match=r"append.only|immutable",
            ):
                await session.execute(text(f"DELETE FROM {table}"))
            await session.rollback()
    await database_engine.dispose()
    with pytest.raises(DBAPIError, match="weekly history exists"):
        await asyncio.to_thread(alembic_command.downgrade, Config("alembic.ini"), "20261028_0018")


async def test_empty_weekly_schema_round_trip_preserves_existing_local_business_history(
    database_engine, monkeypatch
):
    from alembic import command as alembic_command
    from alembic.config import Config

    from investment_os.infrastructure.persistence.models import InstrumentRecord

    monkeypatch.setattr(fixture, "NOW", FRIDAY)
    sessions, _, _, facts, _ = await fixture.setup(database_engine)
    identifier = facts[0].instrument_id
    async with sessions() as session:
        original = await session.get(InstrumentRecord, identifier)
        assert original is not None
        symbol = original.symbol
    await database_engine.dispose()
    await asyncio.to_thread(alembic_command.downgrade, Config("alembic.ini"), "20261028_0018")
    await asyncio.to_thread(alembic_command.upgrade, Config("alembic.ini"), "head")
    async with sessions() as session:
        retained = await session.get(InstrumentRecord, identifier)
        assert retained is not None and retained.symbol == symbol
        assert await session.scalar(select(func.count()).select_from(WeeklyResultRecord)) == 0


async def test_production_weekly_composition_never_uses_http_or_consumes_research_intents(
    database_engine, monkeypatch
):
    import httpx

    from investment_os.worker.weekly_funnel import weekly_worker

    sessions, _, store, _, config, _ = await setup(database_engine, monkeypatch)
    await enable(store, config)

    async def forbidden(*args, **kwargs):
        raise AssertionError("weekly local screening must never make an HTTP request")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    # Production factory, not a stubbed OpportunityService. All data remains in local SQL.
    await weekly_worker(sessions, now=lambda: MONDAY).dispatch_due(now=MONDAY)
    result = (await store.overview()).recent_runs[0]
    assert result.status == "COMPLETE" and result.candidate_count == 1
    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventLogRecord)
                .where(EventLogRecord.event_type.like("%research%"))
            )
            == 0
        )


async def test_late_failure_after_rollback_preserves_successful_weekly_task_and_unique_result(
    database_engine, monkeypatch
):
    sessions, service, store, _, config, _ = await setup(database_engine, monkeypatch)
    await enable(store, config)
    rolled_back, release_failure = asyncio.Event(), asyncio.Event()
    original_prepare = service.prepare_run
    original_record_failure = ReliableJobExecutor._record_failure
    calls = 0

    class FirstWeeklyHandlerFailed(RuntimeError):
        pass

    async def fail_a_then_prepare_b(query):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise FirstWeeklyHandlerFailed("synthetic handler A failed before any commit")
        return await original_prepare(query)

    async def delay_only_a_failure(self, **kwargs):
        if kwargs["error_type"] == "FirstWeeklyHandlerFailed":
            # execute() exits its UOW before this hook: A's rollback released the advisory lock.
            rolled_back.set()
            await release_failure.wait()
        await original_record_failure(self, **kwargs)

    monkeypatch.setattr(service, "prepare_run", fail_a_then_prepare_b)
    monkeypatch.setattr(ReliableJobExecutor, "_record_failure", delay_only_a_failure)
    runner = WeeklyFunnelRunner(sessions, service)
    a = asyncio.create_task(runner.dispatch_due(now=MONDAY))
    try:
        await asyncio.wait_for(rolled_back.wait(), 10)
        assert len(await runner.dispatch_due(now=MONDAY)) == 1  # B obtains the real DB lock.
        async with sessions() as session:
            winner = (await session.scalars(select(TaskRunRecord))).one()
            before = (winner.id, winner.status, winner.attempt, winner.input_hash)
            assert before[1:3] == ("SUCCEEDED", 1)
    finally:
        release_failure.set()
        await asyncio.wait_for(a, 10)
    async with sessions() as session:
        task = (await session.scalars(select(TaskRunRecord))).one()
        assert (task.id, task.status, task.attempt, task.input_hash) == before
        assert task.error_json is None
        assert await session.scalar(select(func.count()).select_from(WeeklyResultRecord)) == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventLogRecord)
                .where(EventLogRecord.event_type == "weekly.completed")
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OutboxEventRecord)
                .where(OutboxEventRecord.topic == "weekly.completed")
            )
            == 1
        )
    assert (await store.overview()).recent_runs[0].status == "COMPLETE"
    assert await runner.dispatch_due(now=MONDAY) == ()
    assert calls == 2  # No third prepare or retry against an already committed weekly result.
