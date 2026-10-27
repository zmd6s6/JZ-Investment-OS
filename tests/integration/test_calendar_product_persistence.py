"""Real SQL, immutable calendar history and Worker unpaid status reports."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from investment_os.application.calendar_product import (
    CalendarImportCommand,
    CalendarModeCommand,
    CalendarProductError,
    CalendarProductService,
)
from investment_os.infrastructure.calendar_product import (
    COMMAND_EVENT,
    REPORT_EVENT,
    PersistedCalendarStatusRunner,
    SqlCalendarProduct,
)
from investment_os.infrastructure.persistence.calendar_models import (
    CalendarConfigurationRecord,
    CalendarImportRecord,
    MarketSessionRecord,
)
from investment_os.infrastructure.persistence.jobs import ReliableJobExecutor
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    EventLogRecord,
    OutboxEventRecord,
    TaskRunRecord,
)

pytestmark = pytest.mark.integration


def command(*, version=0, days="2026-10-23,15:00", source="synthetic-v1"):
    return CalendarImportCommand(
        request_id=uuid4(),
        expected_version=version,
        venue="SSE",
        source_name="合成测试日历",
        source_version=source,
        confirmed_source=True,
        csv_text=f"business_date,close_at\n{days}",
    )


def setup(engine):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    return sessions, CalendarProductService(SqlCalendarProduct(sessions))


async def enable(service, config, *, enabled=True):
    return await service.set_mode(
        config.venue,
        CalendarModeCommand(
            request_id=uuid4(),
            expected_version=config.version,
            enabled=enabled,
            status_only_acknowledgement=True,
        ),
    )


async def test_import_is_paused_atomic_replayable_and_history_immutable(database_engine):
    sessions, service = setup(database_engine)
    request = command()
    first, duplicate = await asyncio.gather(
        service.import_calendar(request), service.import_calendar(request)
    )
    assert first == duplicate and not first.enabled and first.version == 1
    assert (await service.overview()).recent_runs == ()
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(CalendarImportRecord)) == 1
        assert await session.scalar(select(func.count()).select_from(MarketSessionRecord)) == 1
        events = (
            await session.scalars(
                select(EventLogRecord).where(EventLogRecord.event_type == COMMAND_EVENT)
            )
        ).all()
        assert len(events) == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OutboxEventRecord)
                .where(OutboxEventRecord.event_id == events[0].id)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditLogRecord)
                .where(AuditLogRecord.operation == COMMAND_EVENT)
            )
            == 1
        )
    for table in ("market_calendar_import", "market_calendar_session"):
        with pytest.raises(DBAPIError):
            async with database_engine.begin() as connection:
                await connection.execute(text(f"DELETE FROM {table}"))
    active = await enable(service, first)
    revised = await service.import_calendar(command(version=active.version, source="synthetic-v2"))
    assert not revised.enabled and revised.import_id != first.import_id
    assert (
        await service.import_calendar(request) == first
    )  # Receipt precedes latest-version checks.
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(CalendarImportRecord)) == 2


async def test_calendar_request_and_version_conflicts_reject_without_overwrite(database_engine):
    sessions, service = setup(database_engine)
    request = command()
    first = await service.import_calendar(request)
    with pytest.raises(CalendarProductError, match="请求标识"):
        await service.import_calendar(request.model_copy(update={"source_version": "changed"}))
    with pytest.raises(CalendarProductError, match="已被其他操作更新"):
        await service.import_calendar(command(version=0))
    active = await enable(service, first)
    with pytest.raises(CalendarProductError, match="不存在或已更新"):
        await enable(service, first, enabled=False)
    assert (await service.overview()).configurations[0] == active
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(CalendarImportRecord)) == 1


async def test_no_calendar_paused_or_future_calendar_never_dispatches(database_engine):
    sessions, service = setup(database_engine)
    runner = PersistedCalendarStatusRunner(sessions)
    now = datetime(2026, 10, 24, tzinfo=UTC)
    assert await runner.dispatch_due(now=now) == ()
    saved = await service.import_calendar(command(days="2030-01-01,15:00"))
    assert await runner.dispatch_due(now=now) == ()
    await enable(service, saved)
    assert await runner.dispatch_due(now=now) == ()
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(TaskRunRecord)) == 0


async def test_due_calendar_worker_is_bounded_idempotent_and_does_not_create_analysis(
    database_engine,
):
    sessions, service = setup(database_engine)
    config = await service.import_calendar(command(days="2026-10-22,15:00\n2026-10-23,15:00"))
    active = await enable(service, config)
    runner = PersistedCalendarStatusRunner(sessions, max_replay_sessions=1)
    now = datetime(2026, 10, 24, tzinfo=UTC)
    first = await runner.dispatch_due(now=now)
    assert len(first) == 1
    second = await runner.dispatch_due(now=now)
    assert len(second) == 1 and second != first
    assert await runner.dispatch_due(now=now) == ()
    overview = await service.overview()
    assert len(overview.recent_runs) == 2
    assert all(
        r.status == "SUCCEEDED" and r.attempt == 1 and r.report.paid_calls == 0
        for r in overview.recent_runs
    )
    assert all(r.report.report_kind == "CALENDAR_STATUS_ONLY" for r in overview.recent_runs)
    await enable(service, active, enabled=False)
    assert await runner.dispatch_due(now=now) == ()
    async with sessions() as session:
        reports = (
            await session.scalars(
                select(EventLogRecord).where(EventLogRecord.event_type == REPORT_EVENT)
            )
        ).all()
        assert len(reports) == 2
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OutboxEventRecord)
                .where(OutboxEventRecord.event_id.in_([r.id for r in reports]))
            )
            == 2
        )
        assert await session.scalar(select(func.count()).select_from(TaskRunRecord)) == 2
        assert await session.scalar(text("SELECT count(*) FROM agent_run")) == 0
        assert await session.scalar(text("SELECT count(*) FROM investment_decision")) == 0


async def test_calendar_concurrent_workers_have_one_effect(database_engine):
    sessions, service = setup(database_engine)
    await enable(service, await service.import_calendar(command()))
    runner = PersistedCalendarStatusRunner(sessions)
    await asyncio.gather(
        *(runner.dispatch_due(now=datetime(2026, 10, 24, tzinfo=UTC)) for _ in range(3))
    )
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(TaskRunRecord)) == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventLogRecord)
                .where(EventLogRecord.event_type == REPORT_EVENT)
            )
            == 1
        )


async def test_calendar_import_event_failure_rolls_back_all_business_rows(
    database_engine, monkeypatch
):
    sessions, service = setup(database_engine)

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic receipt failure")

    monkeypatch.setattr("investment_os.infrastructure.calendar_product._append_event", fail)
    with pytest.raises(RuntimeError, match="synthetic receipt failure"):
        await service.import_calendar(command())
    async with sessions() as session:
        for table in (
            CalendarImportRecord,
            MarketSessionRecord,
            CalendarConfigurationRecord,
            EventLogRecord,
            OutboxEventRecord,
        ):
            assert await session.scalar(select(func.count()).select_from(table)) == 0


async def test_calendar_pause_between_plan_and_commit_never_publishes_report(
    database_engine, monkeypatch
):
    sessions, service = setup(database_engine)
    active = await enable(service, await service.import_calendar(command()))
    original = ReliableJobExecutor.execute

    async def pause_then_execute(executor, **kwargs):
        await enable(service, active, enabled=False)
        return await original(executor, **kwargs)

    monkeypatch.setattr(ReliableJobExecutor, "execute", pause_then_execute)
    assert (
        await PersistedCalendarStatusRunner(sessions).dispatch_due(
            now=datetime(2026, 10, 24, tzinfo=UTC)
        )
        == ()
    )
    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventLogRecord)
                .where(EventLogRecord.event_type == REPORT_EVENT)
            )
            == 0
        )
        task = await session.scalar(select(TaskRunRecord))
        assert task.status == "FAILED" and task.error_json["type"] == "CalendarConfigurationChanged"


async def test_distinct_concurrent_imports_cannot_overwrite_the_same_base(database_engine):
    sessions, service = setup(database_engine)
    results = await asyncio.gather(
        service.import_calendar(command()),
        service.import_calendar(command(source="other-synthetic")),
        return_exceptions=True,
    )
    assert sum(isinstance(r, CalendarProductError) for r in results) == 1
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(CalendarImportRecord)) == 1


async def test_failed_source_a_can_recover_with_corrected_b_without_rewriting_history(
    database_engine, monkeypatch
):
    sessions, service = setup(database_engine)
    active = await enable(service, await service.import_calendar(command()))
    original = ReliableJobExecutor.execute

    async def pause_then_execute(executor, **kwargs):
        await enable(service, active, enabled=False)
        return await original(executor, **kwargs)

    monkeypatch.setattr(ReliableJobExecutor, "execute", pause_then_execute)
    runner = PersistedCalendarStatusRunner(sessions)
    now = datetime(2026, 10, 24, tzinfo=UTC)
    assert await runner.dispatch_due(now=now) == ()
    failed = (await service.overview()).recent_runs[0]
    assert failed.status == "FAILED" and failed.report is None
    monkeypatch.setattr(ReliableJobExecutor, "execute", original)
    paused = (await service.overview()).configurations[0]
    revised = await service.import_calendar(
        command(version=paused.version, source="corrected-B", days="2026-10-23,15:01")
    )
    await enable(service, revised)
    # Two actual workers must still produce one report for B and retain failed A unchanged.
    await asyncio.gather(*(runner.dispatch_due(now=now) for _ in range(2)))
    overview = await service.overview()
    assert len(overview.recent_runs) == 2
    assert next(r for r in overview.recent_runs if r.task_run_id == failed.task_run_id) == failed
    recovered = next(r for r in overview.recent_runs if r.status == "SUCCEEDED")
    assert recovered.report.source_version == "corrected-B"
    assert recovered.report.calendar_import_id == revised.import_id
    assert recovered.report.calendar_hash == revised.content_hash
    assert recovered.report.paid_calls == 0
    # A third source for the already-completed date never rewrites B or adds a report.
    current = overview.configurations[0]
    third = await service.import_calendar(command(version=current.version, source="revision-C"))
    await enable(service, third)
    assert await runner.dispatch_due(now=now) == ()
    assert (await service.overview()).recent_runs == overview.recent_runs
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(TaskRunRecord)) == 2
        reports = (
            await session.scalars(
                select(EventLogRecord).where(EventLogRecord.event_type == REPORT_EVENT)
            )
        ).all()
        assert len(reports) == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OutboxEventRecord)
                .where(OutboxEventRecord.event_id == reports[0].id)
            )
            == 1
        )


async def test_different_calendar_versions_concurrent_have_at_most_one_success(
    database_engine, monkeypatch
):
    sessions, service = setup(database_engine)
    active = await enable(service, await service.import_calendar(command()))
    original = ReliableJobExecutor.execute
    planned, proceed, old_finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    first_call = True

    async def block_first_plan(executor, **kwargs):
        nonlocal first_call
        if first_call:
            first_call = False
            planned.set()
            await proceed.wait()
            try:
                return await original(executor, **kwargs)
            finally:
                old_finished.set()
        await old_finished.wait()
        return await original(executor, **kwargs)

    monkeypatch.setattr(ReliableJobExecutor, "execute", block_first_plan)
    runner = PersistedCalendarStatusRunner(sessions)
    now = datetime(2026, 10, 24, tzinfo=UTC)
    old_worker = asyncio.create_task(runner.dispatch_due(now=now))
    await asyncio.wait_for(planned.wait(), timeout=5)
    revised = await service.import_calendar(command(version=active.version, source="parallel-B"))
    await enable(service, revised)
    new_worker = asyncio.create_task(runner.dispatch_due(now=now))
    proceed.set()
    await asyncio.gather(old_worker, new_worker)
    runs = (await service.overview()).recent_runs
    assert len(runs) == 2
    assert len([r for r in runs if r.status == "FAILED"]) == 1
    completed = [r for r in runs if r.status == "SUCCEEDED"]
    assert len(completed) == 1 and completed[0].report.source_version == "parallel-B"


async def test_corrected_b_success_before_late_a_rolls_back_a_without_an_empty_success(
    database_engine, monkeypatch
):
    sessions, service = setup(database_engine)
    active = await enable(service, await service.import_calendar(command()))
    original = ReliableJobExecutor.execute
    planned, release_old = asyncio.Event(), asyncio.Event()
    first_call = True

    async def hold_old_until_b_completed(executor, **kwargs):
        nonlocal first_call
        if first_call:
            first_call = False
            planned.set()
            await release_old.wait()
        return await original(executor, **kwargs)

    monkeypatch.setattr(ReliableJobExecutor, "execute", hold_old_until_b_completed)
    runner = PersistedCalendarStatusRunner(sessions)
    now = datetime(2026, 10, 24, tzinfo=UTC)
    old_worker = asyncio.create_task(runner.dispatch_due(now=now))
    await asyncio.wait_for(planned.wait(), timeout=5)
    revised = await service.import_calendar(command(version=active.version, source="first-B"))
    await enable(service, revised)
    completed = await runner.dispatch_due(now=now)
    assert len(completed) == 1
    release_old.set()
    assert await old_worker == ()
    runs = (await service.overview()).recent_runs
    assert len(runs) == 1 and runs[0].status == "SUCCEEDED"
    assert runs[0].report.source_version == "first-B"
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(TaskRunRecord)) == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventLogRecord)
                .where(EventLogRecord.event_type == REPORT_EVENT)
            )
            == 1
        )


async def test_same_calendar_noop_does_not_disable_existing_config_or_create_history(
    database_engine,
):
    sessions, service = setup(database_engine)
    active = await enable(service, await service.import_calendar(command()))
    result = await service.import_calendar(command(version=active.version))
    assert (
        result.enabled and result.version == active.version and result.import_id == active.import_id
    )
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(CalendarImportRecord)) == 1
