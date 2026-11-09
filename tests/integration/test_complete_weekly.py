"""Real version2 scheduling commits complete membership and weekly history atomically."""

import asyncio
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
import test_complete_scope as fixture
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from investment_os.application.calendar_product import CalendarImportCommand, CalendarProductService
from investment_os.application.complete_scope import CompleteScopeService
from investment_os.application.complete_weekly import CompleteWeeklySave
from investment_os.application.opportunity_schedule import WeeklyMode
from investment_os.infrastructure.calendar_product import SqlCalendarProduct
from investment_os.infrastructure.complete_weekly import CompleteWeeklyRunner, SqlCompleteWeekly
from investment_os.infrastructure.opportunity_schedule import SqlWeeklyFunnel
from investment_os.infrastructure.persistence.jobs import ReliableJobExecutor
from investment_os.infrastructure.persistence.models import OutboxEventRecord
from investment_os.infrastructure.universe_models import UniverseRunRecord
from investment_os.infrastructure.weekly_funnel_models import WeeklyResultRecord

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 2, tzinfo=UTC)


async def setup(engine, count=201, *, closed=False, unavailable=False):
    sessions, old, snapshot, command, scope, complete = await fixture.prepare(engine, count)
    run = await complete.run(snapshot.snapshot_id, command)
    calendar = await CalendarProductService(SqlCalendarProduct(sessions)).import_calendar(
        CalendarImportCommand(
            request_id=uuid4(),
            expected_version=0,
            venue="SSE",
            source_name="Synthetic full calendar",
            source_version="v1",
            csv_text="business_date,close_at\n2026-10-23,15:00\n2026-10-27,15:00\n2026-11-02,15:00\n",
            confirmed_source=True,
        )
    )
    store = SqlCompleteWeekly(sessions)
    request = CompleteWeeklySave(
        request_id=uuid4(),
        schedule_id=uuid4(),
        expected_version=0,
        name="Synthetic complete weekly",
        venue="SSE",
        funnel_run_id=run.command.request_id,
        calendar_import_id=calendar.import_id,
        coverage_start=date(2026, 10, 19)
        if unavailable
        else date(2026, 11, 9)
        if closed
        else date(2026, 10, 26),
        coverage_end=date(2026, 10, 25)
        if unavailable
        else date(2026, 11, 15)
        if closed
        else date(2026, 11, 1),
        complete_calendar_acknowledgement=True,
        local_only_acknowledgement=True,
    )
    config = await store.save(request)
    runner = CompleteWeeklyRunner(
        sessions,
        CompleteScopeService(scope, old.funnel, now=lambda: datetime(2026, 11, 16, tzinfo=UTC)),
    )
    return sessions, store, request, config, runner, scope


async def enable(store, config):
    return await store.mode(
        config.schedule_id,
        WeeklyMode(
            request_id=uuid4(),
            expected_version=config.version,
            enabled=True,
            local_only_acknowledgement=True,
        ),
    )


@pytest.mark.parametrize("count", [201, 1000])
async def test_complete_weekly_full_members_default_pause_and_concurrent_replay(
    database_engine, count
):
    sessions, store, request, config, runner, scope = await setup(database_engine, count)
    assert config.schema_version == "2.0" and not config.enabled
    assert len(config.template.instrument_ids) == count
    assert await store.save(request) == config
    assert not (await SqlWeeklyFunnel(sessions).overview()).configurations
    assert await runner.dispatch_due(now=NOW) == ()
    await enable(store, config)
    assert await runner.dispatch_due(now=datetime(2026, 10, 28, tzinfo=UTC)) == ()
    await asyncio.gather(*[runner.dispatch_due(now=NOW) for _ in range(2)])
    result = (await store.overview()).recent_runs[0]
    assert result.status == "DEGRADED" and result.candidate_count == 1
    frozen = await scope.get_complete(result.funnel_run_id)
    assert len(frozen.rows) == count and frozen.model_calls == 0 and frozen.paid_calls == 0
    assert frozen.source.snapshot_id == config.template.snapshot_id
    assert await runner.dispatch_due(now=NOW) == ()
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(WeeklyResultRecord)) == 1


async def test_complete_weekly_outbox_failure_rolls_back_all_then_recovers(database_engine):
    sessions, store, _, config, runner, _scope = await setup(database_engine)
    await enable(store, config)

    def reject(session, *_):
        if any(
            isinstance(row, OutboxEventRecord) and row.topic == "weekly2.completed"
            for row in session.new
        ):
            raise RuntimeError("synthetic weekly outbox failure")

    event.listen(Session, "before_flush", reject)
    try:
        await runner.dispatch_due(now=NOW)
    finally:
        event.remove(Session, "before_flush", reject)
    assert (await store.overview()).recent_runs[0].status == "FAILED"
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(WeeklyResultRecord)) == 0
        assert await session.scalar(select(func.count()).select_from(UniverseRunRecord)) == 1
    await runner.dispatch_due(now=NOW)
    assert (await store.overview()).recent_runs[0].attempt == 2
    assert (await store.overview()).recent_runs[0].funnel_run_id is not None


async def test_complete_weekly_source_not_available_at_prior_week_fails_without_product(
    database_engine,
):
    _, store, _, config, runner, _ = await setup(database_engine, unavailable=True)
    await enable(store, config)
    await runner.dispatch_due(now=NOW)
    result = (await store.overview()).recent_runs[0]
    # Snapshot was imported after the historical session: no partial product.
    assert (
        result.status == "FAILED"
        and result.reason_code == "UniverseError"
        and result.funnel_run_id is None
    )


async def test_complete_weekly_closed_week_skips_without_fake_full_scan(database_engine):
    _, store, _, config, runner, _ = await setup(database_engine, closed=True)
    await enable(store, config)
    await runner.dispatch_due(now=datetime(2026, 11, 16, tzinfo=UTC))
    assert (await store.overview()).recent_runs[0].status == "SKIPPED_CLOSED"


async def test_complete_weekly_pause_after_plan_blocks_stale_commit_then_explicit_resume(
    database_engine, monkeypatch
):
    sessions, store, _, config, runner, _ = await setup(database_engine)
    config = await enable(store, config)
    entered, release = asyncio.Event(), asyncio.Event()
    original = ReliableJobExecutor.execute

    async def held(self, **kwargs):
        entered.set()
        await release.wait()
        return await original(self, **kwargs)

    monkeypatch.setattr(ReliableJobExecutor, "execute", held)
    running = asyncio.create_task(runner.dispatch_due(now=NOW))
    await asyncio.wait_for(entered.wait(), 20)
    paused = await store.mode(
        config.schedule_id,
        WeeklyMode(
            request_id=uuid4(),
            expected_version=config.version,
            enabled=False,
            local_only_acknowledgement=True,
        ),
    )
    release.set()
    await running
    assert (await store.overview()).recent_runs[0].status == "FAILED"
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(WeeklyResultRecord)) == 0
    await enable(store, paused)
    await runner.dispatch_due(now=NOW)
    assert (await store.overview()).recent_runs[0].funnel_run_id is not None


async def test_complete_weekly_calendar_change_blocks_old_scope_and_legacy_mode(database_engine):
    sessions, store, _, config, runner, _ = await setup(database_engine)
    config = await enable(store, config)
    await CalendarProductService(SqlCalendarProduct(sessions)).import_calendar(
        CalendarImportCommand(
            request_id=uuid4(),
            expected_version=1,
            venue="SSE",
            source_name="Synthetic replacement calendar",
            source_version="v2",
            csv_text="business_date,close_at\n2026-10-27,15:00\n",
            confirmed_source=True,
        )
    )
    assert await runner.dispatch_due(now=NOW) == ()
    assert (await store.overview()).configurations[
        0
    ].blocker == "WEEKLY_CALENDAR_CHANGED_OR_MISSING"
    from investment_os.application.opportunities import OpportunityError

    with pytest.raises(OpportunityError):
        await SqlWeeklyFunnel(sessions).mode(
            config.schedule_id,
            WeeklyMode(
                request_id=uuid4(),
                expected_version=config.version,
                enabled=False,
                local_only_acknowledgement=True,
            ),
        )
