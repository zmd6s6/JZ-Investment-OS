"""Real weekly API/DB/Worker local snapshots, immutable history and consent boundaries."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from alembic import command as migration_command
from alembic.config import Config
from analysis_numeric_fixture import seed_numeric
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from investment_os.api.app import create_app
from investment_os.application.calendar_product import CalendarImportCommand, CalendarProductService
from investment_os.application.daily_runtime import DailyMode
from investment_os.application.weekly_review import WeeklyError, WeeklySave
from investment_os.infrastructure.calendar_product import SqlCalendarProduct
from investment_os.infrastructure.manual_market_data import SqlManualMarketData
from investment_os.infrastructure.persistence.models import EventLogRecord, OutboxEventRecord
from investment_os.infrastructure.weekly_review_models import WeeklyReportRecord
from investment_os.infrastructure.weekly_review_reader import SqlWeeklyReader
from investment_os.infrastructure.weekly_review_runner import WeeklyReviewRunner
from investment_os.infrastructure.weekly_review_store import SqlWeeklyReview

pytestmark = pytest.mark.integration


async def setup(engine, *, existing_ids=None):
    if existing_ids is None:
        ids, _ = await seed_numeric(engine)
    else:
        ids = existing_ids
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    first_current = now.date() - timedelta(days=now.weekday())
    last = first_current - timedelta(days=1)
    first = last - timedelta(days=6)
    calendar = await CalendarProductService(SqlCalendarProduct(sessions)).import_calendar(
        CalendarImportCommand(
            request_id=uuid4(),
            expected_version=0,
            venue="SSE",
            source_name="explicit synthetic weekly complete coverage",
            source_version="v1",
            confirmed_source=True,
            csv_text=f"business_date,close_at\n{first},15:00\n{last},15:00\n",
        )
    )
    value = WeeklySave(
        request_id=uuid4(),
        schedule_id=uuid4(),
        expected_version=0,
        name="合成周度组合复核",
        mode="LOCAL_WEEKLY_PORTFOLIO_WATCHLIST_REVIEW",
        frequency="WEEKLY_AFTER_COMPLETE_CALENDAR_WEEK",
        market="SSE",
        portfolio_id=ids["portfolio"],
        portfolio_instrument_ids=(ids["instrument"],),
        watchlist_instrument_ids=(),
        calendar_days={
            first + timedelta(days=i): "OPEN" if i in (0, 6) else "CLOSED" for i in range(7)
        },
        calendar_import_id=calendar.import_id,
        coverage_start=first,
        coverage_end=last,
        quote_source_name="synthetic-205-reference",
        evidence_source_names=("205明确合成数值来源",),
        valid_from=now - timedelta(days=1),
        valid_until=now + timedelta(days=1),
        retention_days=7,
        pause_method="WEEKLY_UI_PAUSE_OR_REVOKE",
        missed_run_policy="LOCAL_CURRENT_KNOWLEDGE_EXPLICIT_WEEK",
        complete_calendar_acknowledgement=True,
        weekly_frequency_acknowledgement=True,
        scope_acknowledgement=True,
        local_only_acknowledgement=True,
        model_profile_ids=(),
        data_profile_ids=(),
        limits=dict(currency="NONE", task_tokens=0, day_tokens=0, task_cost="0", day_cost="0"),
    )
    service = SqlWeeklyReview(sessions)
    runner = WeeklyReviewRunner(sessions, SqlWeeklyReader(SqlManualMarketData(sessions)))
    return sessions, service, runner, value, ids


async def enable(service, command):
    prepared = await service.preview(command, datetime.now(UTC))
    saved = await service.save(command, prepared.content_hash)
    assert not saved.enabled
    return await service.mode(
        command.schedule_id,
        DailyMode(
            request_id=uuid4(), expected_version=saved.version, action="ENABLE", confirmed=True
        ),
    )


async def test_real_weekly_defaults_paused_production_reader_worker_snapshot_and_replay(
    database_engine,
):
    sessions, service, runner, command, ids = await setup(database_engine)
    prepared = await service.preview(command, datetime.now(UTC))
    saved = await service.save(command, prepared.content_hash)
    assert not saved.enabled
    assert await runner.dispatch_due(now=datetime.now(UTC)) == ()
    await service.mode(
        command.schedule_id,
        DailyMode(
            request_id=uuid4(), expected_version=saved.version, action="ENABLE", confirmed=True
        ),
    )
    assert len(await runner.dispatch_due(now=datetime.now(UTC))) == 1
    assert await runner.dispatch_due(now=datetime.now(UTC)) == ()
    reports = await service.reports(command.schedule_id)
    assert len(reports) == 1
    report = reports[0]
    assert report.local_inputs.portfolio.portfolio_id == ids["portfolio"]
    assert report.valuation.nav is not None
    assert report.knowledge_as_of > report.business_as_of
    assert report.baseline_report_id is None
    assert report.holdings[0].core_change is None
    assert report.holdings[0].reentry_assessment == "NOT_PROVIDED"
    assert await service.replay(report.report_id) == report
    assert len(await service.history()) == 1
    async with sessions() as session:
        event = await session.scalar(
            select(EventLogRecord).where(
                EventLogRecord.event_type == "weekly.report",
                EventLogRecord.aggregate_id == report.report_id,
            )
        )
        assert event is not None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OutboxEventRecord)
                .where(OutboxEventRecord.event_id == event.id)
            )
            == 1
        )
        assert await session.scalar(text("SELECT count(*) FROM llm_usage")) == 0
        assert await session.scalar(text("SELECT count(*) FROM daily_configuration")) == 0
        assert await session.scalar(text("SELECT count(*) FROM analysis_run")) == 0


async def test_weekly_api_requires_auth_preview_and_preserves_history_on_terminal_revoke(
    database_engine,
):
    _, service, runner, command, _ = await setup(database_engine)
    app = create_app(weekly_review_service=service, write_api_token="synthetic-weekly-only")
    headers = {"Authorization": "Bearer synthetic-weekly-only"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post(
                "/api/v1/runtime/weekly/preview", json=command.model_dump(mode="json")
            )
        ).status_code == 401
        preview = await client.post(
            "/api/v1/runtime/weekly/preview", headers=headers, json=command.model_dump(mode="json")
        )
        assert preview.status_code == 200
        response = await client.post(
            "/api/v1/runtime/weekly",
            headers=headers,
            json={
                "command": command.model_dump(mode="json"),
                "preview_hash": preview.json()["content_hash"],
            },
        )
        assert response.status_code == 200
        saved = response.json()
        revoked = await service.mode(
            command.schedule_id,
            DailyMode(
                request_id=uuid4(),
                expected_version=saved["version"],
                action="REVOKE",
                confirmed=True,
            ),
        )
        with pytest.raises(WeeklyError, match="WEEKLY_REVOKED"):
            await service.mode(
                command.schedule_id,
                DailyMode(
                    request_id=uuid4(),
                    expected_version=revoked.version,
                    action="ENABLE",
                    confirmed=True,
                ),
            )
        assert await runner.dispatch_due(now=datetime.now(UTC)) == ()


async def test_weekly_history_append_only_and_nonempty_downgrade_preserves_revision(
    database_engine,
):
    sessions, service, runner, command, _ = await setup(database_engine)
    await enable(service, command)
    await runner.dispatch_due(now=datetime.now(UTC))
    assert len(await service.reports()) == 1
    for table in (
        "weekly_local_authorization",
        "weekly_local_member",
        "weekly_local_report",
        "weekly_local_report_evidence",
    ):
        with pytest.raises(DBAPIError, match=r"append-only|immutable"):
            async with sessions() as session, session.begin():
                await session.execute(text(f"DELETE FROM {table}"))
    async with sessions() as session:
        revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
    with pytest.raises(RuntimeError, match="weekly history exists"):
        await asyncio.to_thread(migration_command.downgrade, Config("alembic.ini"), "20261104_0022")
    async with sessions() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == revision
        assert await session.scalar(select(func.count()).select_from(WeeklyReportRecord)) == 1


async def test_weekly_replayed_receipt_cas_and_preview_drift_do_not_silently_expand_scope(
    database_engine,
):
    sessions, service, _, command, ids = await setup(database_engine)
    prepared = await service.preview(command, datetime.now(UTC))
    saved = await service.save(command, prepared.content_hash)
    enabled = await service.mode(
        command.schedule_id,
        DailyMode(
            request_id=uuid4(), expected_version=saved.version, action="ENABLE", confirmed=True
        ),
    )
    assert await service.save(command, prepared.content_hash) == saved
    assert (await service.configurations())[0].enabled
    assert (await service.configurations())[0].version == enabled.version
    with pytest.raises(WeeklyError, match="WEEKLY_REQUEST_CONTENT_CONFLICT"):
        await service.save(command.model_copy(update={"name": "different"}), prepared.content_hash)
    with pytest.raises(WeeklyError, match="WEEKLY_VERSION_CONFLICT"):
        await service.mode(
            command.schedule_id,
            DailyMode(
                request_id=uuid4(), expected_version=saved.version, action="PAUSE", confirmed=True
            ),
        )
    changed = command.model_copy(
        update={"request_id": uuid4(), "expected_version": enabled.version}
    )
    preview = await service.preview(changed, datetime.now(UTC))
    async with sessions() as session, session.begin():
        await session.execute(
            text("UPDATE instrument SET name='changed identity' WHERE id=:id"),
            {"id": ids["instrument"]},
        )
    with pytest.raises(WeeklyError, match="WEEKLY_PREVIEW_STALE"):
        await service.save(changed, preview.content_hash)
    async with sessions() as session:
        assert await session.scalar(text("SELECT count(*) FROM weekly_local_authorization")) == 1


async def test_weekly_outbox_failure_is_atomic_then_retries_same_business_once(
    database_engine, monkeypatch
):
    import investment_os.infrastructure.weekly_review_runner as module

    sessions, service, runner, command, _ = await setup(database_engine)
    await enable(service, command)
    original = module.emit

    async def broken(*args, **kwargs):
        raise RuntimeError("synthetic outbox failure")

    monkeypatch.setattr(module, "emit", broken)
    assert await runner.dispatch_due(now=datetime.now(UTC)) == ()
    assert await service.reports() == ()
    async with sessions() as session:
        assert await session.scalar(text("SELECT count(*) FROM weekly_local_report_evidence")) == 0
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventLogRecord)
                .where(EventLogRecord.event_type == "weekly.report")
            )
            == 0
        )
    assert (await service.runs())[0].status == "FAILED"
    monkeypatch.setattr(module, "emit", original)
    assert len(await runner.dispatch_due(now=datetime.now(UTC))) == 1
    assert len(await service.reports()) == 1
    assert (await service.runs())[0].attempt == 2
    assert await runner.dispatch_due(now=datetime.now(UTC)) == ()


async def test_weekly_three_failed_local_attempts_stop_without_partial_or_paid_output(
    database_engine, monkeypatch
):
    import investment_os.infrastructure.weekly_review_runner as module

    _, service, runner, command, _ = await setup(database_engine)
    await enable(service, command)

    async def broken(*args, **kwargs):
        raise RuntimeError("synthetic always unavailable")

    monkeypatch.setattr(module, "emit", broken)
    for _ in range(4):
        assert await runner.dispatch_due(now=datetime.now(UTC)) == ()
    assert len(await service.runs()) == 1
    assert (await service.runs())[0].attempt == 3
    assert (await service.runs())[0].status == "FAILED"
    assert await service.reports() == ()


async def test_weekly_permission_expiring_after_awaited_capture_commits_no_report(database_engine):
    sessions, service, _, command, _ = await setup(database_engine)
    await enable(service, command)
    clock = {"now": datetime.now(UTC)}

    class ExpiringReader(SqlWeeklyReader):
        async def read(self, *args, **kwargs):
            result = await super().read(*args, **kwargs)
            clock["now"] = command.valid_until
            return result

    runner = WeeklyReviewRunner(
        sessions, ExpiringReader(SqlManualMarketData(sessions)), clock=lambda: clock["now"]
    )
    assert await runner.dispatch_due(now=clock["now"]) == ()
    assert await service.reports() == ()
    assert (await service.runs())[0].status == "FAILED"


async def test_weekly_expired_report_only_exposes_history_and_replay_fails_closed(
    database_engine, monkeypatch
):
    import investment_os.infrastructure.weekly_review_store as module

    _, service, runner, command, _ = await setup(database_engine)
    await enable(service, command)
    await runner.dispatch_due(now=datetime.now(UTC))
    report = (await service.reports())[0]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return report.usable_until

    monkeypatch.setattr(module, "datetime", Clock)
    assert await service.reports() == ()
    history = await service.history()
    assert len(history) == 1 and not history[0].usable
    with pytest.raises(WeeklyError, match="WEEKLY_REPORT_EXPIRED_HISTORY_PRESERVED"):
        await service.replay(report.report_id)


async def test_weekly_existing_decision_risk_thesis_are_read_without_new_model_or_approval(
    database_engine,
):
    from test_analysis_decision_bridge import complete_analysis

    from investment_os.infrastructure.analysis_decision_bridge import SqlAnalysisDecisionBridge

    sessions, _, original, preparation, calls, client, _, _ = await complete_analysis(
        database_engine
    )
    try:
        decision = await SqlAnalysisDecisionBridge(sessions).prepare(preparation)
        assert decision.status == "PENDING_APPROVAL"
        _, service, runner, command, _ = await setup(
            database_engine,
            existing_ids={"portfolio": original.portfolio_id, "instrument": original.instrument_id},
        )
        command = command.model_copy(
            update={"evidence_source_names": ("205明确合成数值来源", "206明确合成规则资料")}
        )
        before_calls = len(calls)
        await enable(service, command)
        assert len(await runner.dispatch_due(now=datetime.now(UTC))) == 1
        report = (await service.reports())[0]
        refs = report.holdings[0].references
        assert {ref.kind for ref in refs} == {"THESIS", "ANALYSIS", "RISK", "DECISION"}
        assert next(ref for ref in refs if ref.kind == "DECISION").record_id == decision.decision_id
        assert all(ref.unknowns for ref in refs)
        assert len(calls) == before_calls
        async with sessions() as session:
            assert (
                await session.scalar(text("SELECT count(*) FROM weekly_local_report_reference"))
                == 4
            )
            assert await session.scalar(text("SELECT count(*) FROM investment_decision")) == 1
            assert await session.scalar(text("SELECT count(*) FROM decision_approval")) == 0
            assert await session.scalar(text("SELECT count(*) FROM decision_execution")) == 0
    finally:
        await client.aclose()


async def test_weekly_snapshot_baseline_compares_real_core_tactical_changes(database_engine):
    sessions, service, _, command, ids = await setup(database_engine)
    prior_end = command.coverage_start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=6)
    calendar = await CalendarProductService(SqlCalendarProduct(sessions)).import_calendar(
        CalendarImportCommand(
            request_id=uuid4(),
            expected_version=1,
            venue="SSE",
            source_name="explicit two month synthetic coverage",
            source_version="v2",
            confirmed_source=True,
            csv_text="business_date,close_at\n"
            + "".join(
                f"{day},15:00\n"
                for day in (prior_start, prior_end, command.coverage_start, command.coverage_end)
            ),
        )
    )
    command = command.model_copy(
        update={
            "calendar_import_id": calendar.import_id,
            "coverage_start": prior_start,
            "calendar_days": {
                prior_start + timedelta(days=i): "OPEN" if i in (0, 6, 7, 13) else "CLOSED"
                for i in range(14)
            },
        }
    )
    await enable(service, command)
    runner = WeeklyReviewRunner(
        sessions, SqlWeeklyReader(SqlManualMarketData(sessions)), max_periods=1
    )
    assert len(await runner.dispatch_due(now=datetime.now(UTC))) == 1
    first = (await service.reports())[0]
    async with sessions() as session, session.begin():
        await session.execute(
            text(
                "UPDATE position SET core_quantity=core_quantity+5, "
                "tactical_quantity=tactical_quantity-2, version=version+1 "
                "WHERE portfolio_id=:id AND instrument_id=:instrument"
            ),
            {"id": ids["portfolio"], "instrument": ids["instrument"]},
        )
    assert len(await runner.dispatch_due(now=datetime.now(UTC))) == 1
    latest = (await service.reports())[0]
    assert latest.baseline_report_id == first.report_id
    assert latest.baseline_status == "COMPARABLE_BASELINE"
    assert Decimal(latest.holdings[0].core_change) == 5
    assert Decimal(latest.holdings[0].tactical_change) == -2
    assert await service.replay(first.report_id) == first
    assert await runner.dispatch_due(now=datetime.now(UTC)) == ()


async def test_weekly_missing_quote_has_no_fabricated_zero_nav(database_engine):
    _, service, runner, command, _ = await setup(database_engine)
    command = command.model_copy(update={"quote_source_name": "explicit missing synthetic source"})
    await enable(service, command)
    assert len(await runner.dispatch_due(now=datetime.now(UTC))) == 1
    report = (await service.reports())[0]
    assert report.phase == "DEGRADED" and report.valuation.nav is None
    assert report.valuation.cash_weight is None
    assert report.holdings[0].quote_status != "AVAILABLE"
    assert report.holdings[0].reentry_assessment == "NOT_PROVIDED"


async def test_weekly_explicit_no_session_month_skips_without_invented_market_close(
    database_engine,
):
    _, service, runner, command, _ = await setup(database_engine)
    closed_end = command.coverage_start - timedelta(days=1)
    closed = command.model_copy(
        update={
            "coverage_start": closed_end - timedelta(days=6),
            "coverage_end": closed_end,
            "calendar_days": {closed_end - timedelta(days=i): "CLOSED" for i in range(7)},
        }
    )
    await enable(service, closed)
    assert len(await runner.dispatch_due(now=datetime.now(UTC))) == 1
    report = (await service.reports())[0]
    assert report.phase == "CLOSED_WEEK_SKIPPED"
    assert report.business_as_of is None and report.local_inputs is None
    assert report.holdings == () and report.valuation is None


@pytest.mark.parametrize("problem", ["missing_date", "invented_open", "hidden_open", "extra_date"])
async def test_weekly_independently_checks_every_persisted_calendar_date(database_engine, problem):
    _, service, _, command, _ = await setup(database_engine)
    manifest = dict(command.calendar_days)
    if problem == "missing_date":
        manifest.pop(command.coverage_start + timedelta(days=2))
    elif problem == "invented_open":
        manifest[command.coverage_start + timedelta(days=2)] = "OPEN"
    elif problem == "hidden_open":
        manifest[command.coverage_start] = "CLOSED"
    else:
        manifest[command.coverage_end + timedelta(days=1)] = "CLOSED"
    with pytest.raises(WeeklyError, match="MANIFEST"):
        await service.preview(
            command.model_copy(update={"calendar_days": manifest}), datetime.now(UTC)
        )
    assert await service.configurations() == ()


async def test_weekly_watchlist_membership_and_provenance_are_real_and_frozen(database_engine):
    from investment_os.infrastructure.persistence.models import WatchlistItemRecord
    from investment_os.infrastructure.weekly_review_store import common

    sessions, service, runner, command, ids = await setup(database_engine)
    command = command.model_copy(update={"watchlist_instrument_ids": (ids["instrument"],)})
    with pytest.raises(WeeklyError, match="WATCHLIST_SCOPE_CHANGED"):
        await service.preview(command, datetime.now(UTC))
    async with sessions() as session, session.begin():
        session.add(
            WatchlistItemRecord(
                instrument_id=ids["instrument"], added_at=datetime.now(UTC), **common(uuid4())
            )
        )
    await enable(service, command)
    assert len(await runner.dispatch_due(now=datetime.now(UTC))) == 1
    report = (await service.reports())[0]
    assert report.local_inputs.members[0].in_watchlist
    assert report.local_inputs.members[0].in_portfolio
    assert (
        report.local_inputs.quote_evidence_ids[ids["instrument"]]
        in report.evidence_diff.visible_ids
    )
    async with sessions() as session, session.begin():
        await session.execute(
            text("DELETE FROM watchlist_item WHERE instrument_id=:id"), {"id": ids["instrument"]}
        )
    assert (await service.configurations())[0].blocker == "WEEKLY_WATCHLIST_SCOPE_CHANGED"
    assert await service.replay(report.report_id) == report


async def test_weekly_empty_migration_downgrade_upgrade_retains_old_monthly_history(
    database_engine,
):
    async with database_engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM weekly_local_authorization")) == 0
    await asyncio.to_thread(migration_command.downgrade, Config("alembic.ini"), "20261111_0026")
    await asyncio.to_thread(migration_command.upgrade, Config("alembic.ini"), "head")
    async with database_engine.connect() as conn:
        assert await conn.scalar(text("SELECT version_num FROM alembic_version")) == "20261117_0028"
        assert await conn.scalar(text("SELECT count(*) FROM weekly_local_report")) == 0


async def test_weekly_watchlist_only_member_missing_quote_never_becomes_portfolio_or_zero(
    database_engine,
):
    from investment_os.infrastructure.persistence.models import (
        InstrumentRecord,
        WatchlistItemRecord,
    )
    from investment_os.infrastructure.weekly_review_store import common

    sessions, service, runner, command, ids = await setup(database_engine)
    watch_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            InstrumentRecord(
                id=watch_id,
                symbol="629408",
                exchange="SSE",
                name="合成仅观察无报价",
                asset_type="EQUITY",
                currency="CNY",
                **common(uuid4()),
            )
        )
        await session.flush()
        session.add(
            WatchlistItemRecord(
                instrument_id=watch_id, added_at=datetime.now(UTC), **common(uuid4())
            )
        )
    command = command.model_copy(update={"watchlist_instrument_ids": (watch_id,)})
    await enable(service, command)
    assert len(await runner.dispatch_due(now=datetime.now(UTC))) == 1
    report = (await service.reports())[0]
    watched = next(
        member for member in report.local_inputs.members if member.instrument_id == watch_id
    )
    assert watched.in_watchlist and not watched.in_portfolio
    assert len(report.holdings) == 1 and report.holdings[0].instrument_id == ids["instrument"]
    quote = next(value for value in report.quotes if value.instrument_id == watch_id)
    assert quote.status != "AVAILABLE" and quote.quote is None
    assert watch_id not in report.local_inputs.quote_evidence_ids
    assert (
        report.valuation.nav is not None
    )  # Missing watch price is not an invented position/value.
    assert await service.replay(report.report_id) == report


async def test_weekly_nonempty_0027_upgrade_preserves_legacy_authorization_without_reauthorizing(
    database_engine,
):
    from investment_os.infrastructure.persistence.models import TaskRunRecord
    from investment_os.infrastructure.weekly_review_store import common

    sessions, service, runner, command, _ = await setup(database_engine)
    await asyncio.to_thread(migration_command.downgrade, Config("alembic.ini"), "20261115_0027")
    revision = uuid4()
    async with sessions() as session, session.begin():
        await session.execute(
            text("INSERT INTO weekly_local_configuration(id) VALUES (:id)"),
            {"id": command.schedule_id},
        )
        await session.execute(
            text(
                "INSERT INTO weekly_local_authorization "
                "(id,schedule_id,version,portfolio_id,calendar_import_id,valid_from,valid_until,"
                "coverage_start,coverage_end,authorization_json,content_hash) "
                "VALUES (:id,:schedule,1,:portfolio,:calendar,:start,:end,:first,:last,"
                '\'{"legacy":"preserve original without inventing permission"}\'::jsonb,:hash)'
            ),
            dict(
                id=revision,
                schedule=command.schedule_id,
                portfolio=command.portfolio_id,
                calendar=command.calendar_import_id,
                start=command.valid_from,
                end=command.valid_until,
                first=command.coverage_start,
                last=command.coverage_end,
                hash="b" * 64,
            ),
        )
        await session.execute(
            text("UPDATE weekly_local_configuration SET current_revision_id=:id,version=1"),
            {"id": revision},
        )
        task_id, report_id = uuid4(), uuid4()
        session.add(
            TaskRunRecord(
                id=task_id,
                task_name="weekly_portfolio_review",
                scheduled_for=datetime.now(UTC),
                status="SUCCEEDED",
                attempt=1,
                idempotency_key=f"weekly:{command.schedule_id}:{revision}:legacy",
                input_hash="b" * 64,
                started_at=datetime.now(UTC),
                **common(uuid4()),
            )
        )
        await session.flush()
        await session.execute(
            text(
                "INSERT INTO weekly_local_report(id,schedule_id,revision_id,task_run_id,week_start,"
                "week_end,knowledge_as_of,recorded_at,report_json,content_hash) "
                "VALUES (:id,:schedule,:revision,:task,:first,:last,:now,:now,"
                '\'{"legacy":"original report"}\'::jsonb,:hash)'
            ),
            dict(
                id=report_id,
                schedule=command.schedule_id,
                revision=revision,
                task=task_id,
                first=command.coverage_start,
                last=command.coverage_end,
                now=datetime.now(UTC),
                hash="c" * 64,
            ),
        )
    await asyncio.to_thread(migration_command.upgrade, Config("alembic.ini"), "head")
    old = (await service.configurations())[0]
    assert old.prepared is None and not old.enabled
    assert old.blocker == "WEEKLY_LEGACY_UNVERIFIED_CREATE_NEW_AUTHORIZATION"
    assert await runner.dispatch_due(now=datetime.now(UTC)) == ()
    with pytest.raises(WeeklyError, match="LEGACY_UNVERIFIED"):
        await service.mode(
            command.schedule_id,
            DailyMode(request_id=uuid4(), expected_version=1, action="ENABLE", confirmed=True),
        )
    revoked = await service.mode(
        command.schedule_id,
        DailyMode(request_id=uuid4(), expected_version=1, action="REVOKE", confirmed=True),
    )
    assert revoked.revoked and revoked.prepared is None and revoked.version == 2
    with pytest.raises(RuntimeError, match="weekly history exists"):
        await asyncio.to_thread(migration_command.downgrade, Config("alembic.ini"), "20261115_0027")
    await asyncio.to_thread(migration_command.upgrade, Config("alembic.ini"), "head")
    async with sessions() as session:
        row = (
            await session.execute(
                text("SELECT authorization_json,content_hash FROM weekly_local_authorization")
            )
        ).one()
        assert row.authorization_json == {
            "legacy": "preserve original without inventing permission"
        }
        assert row.content_hash == "b" * 64
    assert len(await service.configurations()) == 1
    history = await service.history()
    assert len(history) == 1 and history[0].report_id == report_id
    assert not history[0].usable and history[0].content_hash == "c" * 64
    with pytest.raises(WeeklyError, match="SCHEMA_OR_HASH_INVALID"):
        await service.replay(report_id)
    async with sessions() as session:
        original = (
            await session.execute(text("SELECT report_json FROM weekly_local_report"))
        ).scalar_one()
        assert original == {"legacy": "original report"}
