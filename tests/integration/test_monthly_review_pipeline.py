"""Real monthly API/DB/Worker local snapshots, immutable history and consent boundaries."""

import asyncio
from datetime import UTC, datetime, timedelta
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
from investment_os.application.monthly_review import MonthlyError, MonthlySave
from investment_os.infrastructure.calendar_product import SqlCalendarProduct
from investment_os.infrastructure.manual_market_data import SqlManualMarketData
from investment_os.infrastructure.monthly_review_models import MonthlyReportRecord
from investment_os.infrastructure.monthly_review_reader import SqlMonthlyReader
from investment_os.infrastructure.monthly_review_runner import MonthlyReviewRunner
from investment_os.infrastructure.monthly_review_store import SqlMonthlyReview
from investment_os.infrastructure.persistence.models import EventLogRecord, OutboxEventRecord

pytestmark = pytest.mark.integration


async def setup(engine):
    ids, _ = await seed_numeric(engine)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    first_current = now.date().replace(day=1)
    last = first_current - timedelta(days=1)
    first = last.replace(day=1)
    calendar = await CalendarProductService(SqlCalendarProduct(sessions)).import_calendar(
        CalendarImportCommand(
            request_id=uuid4(),
            expected_version=0,
            venue="SSE",
            source_name="explicit synthetic monthly complete coverage",
            source_version="v1",
            confirmed_source=True,
            csv_text=f"business_date,close_at\n{first},15:00\n{last},15:00\n",
        )
    )
    value = MonthlySave(
        request_id=uuid4(),
        schedule_id=uuid4(),
        expected_version=0,
        name="合成月度组合复核",
        mode="LOCAL_MONTHLY_REVIEW",
        frequency="MONTHLY_AFTER_COMPLETE_CALENDAR_MONTH",
        market="SSE",
        portfolio_id=ids["portfolio"],
        portfolio_instrument_ids=(ids["instrument"],),
        calendar_import_id=calendar.import_id,
        coverage_start=first,
        coverage_end=last,
        quote_source_name="synthetic-205-reference",
        evidence_source_names=("205明确合成数值来源",),
        valid_from=now - timedelta(days=1),
        valid_until=now + timedelta(days=1),
        retention_days=7,
        pause_method="MONTHLY_UI_PAUSE_OR_REVOKE",
        missed_run_policy="LOCAL_CURRENT_KNOWLEDGE_EXPLICIT_PERIOD",
        complete_calendar_acknowledgement=True,
        monthly_frequency_acknowledgement=True,
        scope_acknowledgement=True,
        local_only_acknowledgement=True,
        model_profile_ids=(),
        data_profile_ids=(),
        limits=dict(currency="NONE", task_tokens=0, day_tokens=0, task_cost="0", day_cost="0"),
    )
    service = SqlMonthlyReview(sessions)
    runner = MonthlyReviewRunner(sessions, SqlMonthlyReader(SqlManualMarketData(sessions)))
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


async def test_real_monthly_defaults_paused_production_reader_worker_snapshot_and_replay(
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
                EventLogRecord.event_type == "monthly.report",
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


async def test_monthly_api_requires_auth_preview_and_preserves_history_on_terminal_revoke(
    database_engine,
):
    _, service, runner, command, _ = await setup(database_engine)
    app = create_app(monthly_review_service=service, write_api_token="synthetic-monthly-only")
    headers = {"Authorization": "Bearer synthetic-monthly-only"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post(
                "/api/v1/runtime/monthly/preview", json=command.model_dump(mode="json")
            )
        ).status_code == 401
        preview = await client.post(
            "/api/v1/runtime/monthly/preview", headers=headers, json=command.model_dump(mode="json")
        )
        assert preview.status_code == 200
        response = await client.post(
            "/api/v1/runtime/monthly",
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
        with pytest.raises(MonthlyError, match="MONTHLY_REVOKED"):
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


async def test_monthly_history_append_only_and_nonempty_downgrade_preserves_revision(
    database_engine,
):
    sessions, service, runner, command, _ = await setup(database_engine)
    await enable(service, command)
    await runner.dispatch_due(now=datetime.now(UTC))
    assert len(await service.reports()) == 1
    for table in (
        "monthly_authorization_revision",
        "monthly_authorized_member",
        "monthly_portfolio_report",
        "monthly_report_evidence",
    ):
        with pytest.raises(DBAPIError, match=r"append-only|immutable"):
            async with sessions() as session, session.begin():
                await session.execute(text(f"DELETE FROM {table}"))
    async with sessions() as session:
        revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
    with pytest.raises(RuntimeError, match="monthly history exists"):
        await asyncio.to_thread(migration_command.downgrade, Config("alembic.ini"), "20261104_0022")
    async with sessions() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == revision
        assert await session.scalar(select(func.count()).select_from(MonthlyReportRecord)) == 1
