"""Monthly comparisons require actual unexpired local captures, never closed-period skips."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_monthly_review_pipeline import enable, setup

from investment_os.application.calendar_product import CalendarImportCommand, CalendarProductService
from investment_os.infrastructure.calendar_product import SqlCalendarProduct
from investment_os.infrastructure.manual_market_data import SqlManualMarketData
from investment_os.infrastructure.monthly_review_reader import SqlMonthlyReader
from investment_os.infrastructure.monthly_review_runner import MonthlyReviewRunner

pytestmark = pytest.mark.integration


async def monthly_sequence(engine, open_months):
    sessions, service, _, command, ids = await setup(engine)
    months = [command.coverage_start]
    for _ in range(len(open_months) - 1):
        months.insert(0, (months[0] - timedelta(days=1)).replace(day=1))
    calendar = await CalendarProductService(SqlCalendarProduct(sessions)).import_calendar(
        CalendarImportCommand(
            request_id=uuid4(),
            expected_version=1,
            venue="SSE",
            source_name="explicit synthetic comparable-month audit",
            source_version="v2",
            confirmed_source=True,
            csv_text="business_date,close_at\n"
            + "".join(
                f"{month},15:00\n"
                for month, opened in zip(months, open_months, strict=True)
                if opened
            ),
        )
    )
    now = datetime.now(UTC)
    command = command.model_copy(
        update={
            "calendar_import_id": calendar.import_id,
            "coverage_start": months[0],
            "valid_until": now + timedelta(days=30),
            "retention_days": 1,
        }
    )
    await enable(service, command)
    return sessions, service, command, ids, now


async def test_closed_month_cannot_be_the_first_real_capture_baseline(database_engine):
    sessions, service, command, _, now = await monthly_sequence(database_engine, (False, True))
    runner = MonthlyReviewRunner(
        sessions, SqlMonthlyReader(SqlManualMarketData(sessions)), max_periods=1, clock=lambda: now
    )
    assert len(await runner.dispatch_due(now=now)) == 1
    skipped = max(await service.reports(command.schedule_id), key=lambda row: row.period_start)
    assert skipped.phase == "CLOSED_MONTH_SKIPPED" and skipped.local_inputs is None
    assert len(await runner.dispatch_due(now=now)) == 1
    report = max(await service.reports(command.schedule_id), key=lambda row: row.period_start)
    assert report.local_inputs is not None
    assert report.baseline_report_id is None
    assert report.baseline_status == "FIRST_RUN_NO_BASELINE"
    assert report.evidence_diff.baseline_report_id is None
    assert report.holdings[0].core_change is None
    assert await service.replay(skipped.report_id) == skipped


async def test_open_closed_open_compares_the_previous_real_capture_and_preserves_skips(
    database_engine,
):
    sessions, service, command, ids, now = await monthly_sequence(
        database_engine, (True, False, True)
    )
    runner = MonthlyReviewRunner(
        sessions, SqlMonthlyReader(SqlManualMarketData(sessions)), max_periods=1, clock=lambda: now
    )
    assert len(await runner.dispatch_due(now=now)) == 1
    first = max(await service.reports(command.schedule_id), key=lambda row: row.period_start)
    assert len(await runner.dispatch_due(now=now)) == 1
    skipped = max(await service.reports(command.schedule_id), key=lambda row: row.period_start)
    assert skipped.phase == "CLOSED_MONTH_SKIPPED"
    assert skipped.baseline_report_id is None
    assert skipped.baseline_status == "FIRST_RUN_NO_BASELINE"
    async with sessions() as session, session.begin():
        await session.execute(
            text(
                "UPDATE position SET core_quantity=core_quantity+5, "
                "tactical_quantity=tactical_quantity-2, version=version+1 "
                "WHERE portfolio_id=:id AND instrument_id=:instrument"
            ),
            {"id": ids["portfolio"], "instrument": ids["instrument"]},
        )
    assert len(await runner.dispatch_due(now=now)) == 1
    report = max(await service.reports(command.schedule_id), key=lambda row: row.period_start)
    assert report.baseline_report_id == first.report_id
    assert report.baseline_status == "COMPARABLE_BASELINE"
    assert report.evidence_diff.baseline_report_id == first.report_id
    assert Decimal(report.holdings[0].core_change) == 5
    assert Decimal(report.holdings[0].tactical_change) == -2
    assert await service.replay(first.report_id) == first
    assert await service.replay(skipped.report_id) == skipped


@pytest.mark.parametrize("expiry_offset", (-1, 0, 1))
async def test_monthly_prior_retention_uses_actual_knowledge_time_not_stale_poll_time(
    database_engine, expiry_offset
):
    sessions, service, command, _, now = await monthly_sequence(database_engine, (True, True))
    clock = [now]
    runner = MonthlyReviewRunner(
        sessions,
        SqlMonthlyReader(SqlManualMarketData(sessions)),
        max_periods=1,
        clock=lambda: clock[0],
    )
    assert len(await runner.dispatch_due(now=now)) == 1
    first = max(await service.reports(command.schedule_id), key=lambda row: row.period_start)
    clock[0] = first.usable_until + timedelta(microseconds=expiry_offset)
    assert len(await runner.dispatch_due(now=now)) == 1
    report = max(await service.reports(command.schedule_id), key=lambda row: row.period_start)
    if expiry_offset < 0:
        assert report.baseline_report_id == first.report_id
        assert report.baseline_status == "COMPARABLE_BASELINE"
    else:
        assert report.baseline_report_id is None
        assert report.baseline_status == "FIRST_RUN_NO_BASELINE"
        assert report.evidence_diff.baseline_report_id is None
        assert report.holdings[0].core_change is None
    # Expiration cannot erase the old immutable payload or its hash.
    async with sessions() as session:
        stored = (
            await session.execute(
                text("SELECT content_hash FROM monthly_portfolio_report WHERE id=:id"),
                {"id": first.report_id},
            )
        ).scalar_one()
        assert stored == first.content_hash
