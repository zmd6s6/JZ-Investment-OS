from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from investment_os.application.weekly_review import WeeklyReviewSave, WeeklyReviewError, completed_weeks


def command(**changes):
    data = dict(
        request_id=uuid4(), schedule_id=uuid4(), expected_version=0,
        name="合成周度本地复核", mode="LOCAL_WEEKLY_PORTFOLIO_WATCHLIST_REVIEW",
        frequency="WEEKLY_AFTER_COMPLETE_CALENDAR_WEEK", market="SSE",
        portfolio_id=uuid4(), portfolio_instrument_ids=[uuid4()],
        watchlist_instrument_ids=[uuid4()], calendar_import_id=uuid4(),
        coverage_start="2026-11-09", coverage_end="2026-11-15",
        quote_source_name="synthetic local", evidence_source_names=[],
        valid_from="2026-11-01T00:00:00Z", valid_until="2026-12-01T00:00:00Z",
        retention_days=30, pause_method="WEEKLY_UI_PAUSE_OR_REVOKE",
        missed_run_policy="LOCAL_CURRENT_KNOWLEDGE_EXPLICIT_WEEK",
        complete_calendar_acknowledgement=True, weekly_frequency_acknowledgement=True,
        scope_acknowledgement=True, local_only_acknowledgement=True,
        model_profile_ids=[], data_profile_ids=[],
        limits=dict(currency="NONE", task_tokens=0, day_tokens=0, task_cost="0", day_cost="0"),
    )
    return WeeklyReviewSave.model_validate(data | changes)


def test_weekly_distinct_zero_cost_consent_normal():
    value = command()
    assert value.frequency == "WEEKLY_AFTER_COMPLETE_CALENDAR_WEEK"
    assert value.model_profile_ids == () and value.data_profile_ids == ()
    assert value.portfolio_instrument_ids != value.watchlist_instrument_ids


@pytest.mark.parametrize("changes", [
    {"coverage_start": "2026-11-10"}, {"coverage_end": "2026-11-14"},
    {"weekly_frequency_acknowledgement": False},
    {"complete_calendar_acknowledgement": False},
    {"frequency": "MONTHLY_AFTER_COMPLETE_CALENDAR_MONTH"},
    {"mode": "SCHEDULED_SHADOW"},
    {"model_profile_ids": [uuid4()]}, {"data_profile_ids": [uuid4()]},
    {"limits": dict(currency="NONE", task_tokens=1, day_tokens=0, task_cost="0", day_cost="0")},
    {"valid_until": "2026-10-01T00:00:00Z"},
])
def test_weekly_partial_period_missing_consent_or_paid_scope_fails_closed(changes):
    with pytest.raises(ValidationError):
        command(**changes)


def test_weekly_duplicate_membership_is_rejected_but_cross_list_membership_is_allowed():
    member = uuid4()
    with pytest.raises(ValidationError):
        command(portfolio_instrument_ids=[member, member])
    with pytest.raises(ValidationError):
        command(watchlist_instrument_ids=[member, member])
    assert command(portfolio_instrument_ids=[member], watchlist_instrument_ids=[member])


def test_weekly_timezone_boundary_only_after_sunday():
    start, end = date(2026, 11, 9), date(2026, 11, 15)
    assert completed_weeks(start, end, datetime(2026, 11, 15, 15, 59, tzinfo=UTC), "SSE") == ()
    assert completed_weeks(start, end, datetime(2026, 11, 15, 16, tzinfo=UTC), "SSE") == ((start, end),)


def test_weekly_multiple_weeks_and_invalid_naive_time():
    start, end = date(2026, 11, 9), date(2026, 11, 22)
    assert completed_weeks(start, end, datetime(2026, 11, 16, tzinfo=UTC), "SZSE") == ((start, date(2026, 11, 15)),)
    with pytest.raises(WeeklyReviewError, match="WEEKLY_TIMEZONE_REQUIRED"):
        completed_weeks(start, end, datetime(2026, 11, 23), "SSE")
    with pytest.raises(WeeklyReviewError, match="WEEKLY_COMPLETE_PERIOD_REQUIRED"):
        completed_weeks(start, date(2026, 11, 21), datetime(2026, 11, 23, tzinfo=UTC), "SSE")


def test_weekly_standalone_enumeration_rejects_unbounded_range():
    # The Worker helper must enforce the same limit as the save DTO, even if
    # invoked without passing through API validation.
    with pytest.raises(WeeklyReviewError, match="WEEKLY_COMPLETE_PERIOD_REQUIRED"):
        completed_weeks(
            date(2026, 11, 9), date(2028, 11, 12),
            datetime(2028, 11, 13, tzinfo=UTC), "SSE",
        )


@pytest.mark.parametrize("market", ["NYSE", "US_EQUITIES"])
def test_weekly_standalone_worker_rejects_unsupported_market(market):
    # Persisted/legacy task payloads must fail with a named weekly error even
    # when they bypass the API DTO's SSE/SZSE validation.
    with pytest.raises(WeeklyReviewError, match="WEEKLY_UNSUPPORTED_MARKET"):
        completed_weeks(
            date(2026, 11, 9), date(2026, 11, 15),
            datetime(2026, 11, 16, tzinfo=UTC), market,
        )


def test_weekly_worker_preflight_allows_only_enabled_current_authorization():
    from investment_os.application.weekly_review import eligible_weekly_periods
    consent = command()
    now = datetime(2026, 11, 16, tzinfo=UTC)
    params = dict(
        persisted_calendar_import_id=consent.calendar_import_id,
        persisted_members=consent.portfolio_instrument_ids,
        persisted_watchlist_members=consent.watchlist_instrument_ids,
        calendar_coverage_attested=True,
        calendar_sessions=(date(2026, 11, 9), date(2026, 11, 10)),
    )
    assert eligible_weekly_periods(consent, now, enabled=True, revoked=False, **params) == (
        (date(2026, 11, 9), date(2026, 11, 15)),
    )
    assert eligible_weekly_periods(consent, now, enabled=False, revoked=False, **params) == ()
    assert eligible_weekly_periods(consent, now, enabled=True, revoked=True, **params) == ()


def test_weekly_worker_preflight_rejects_calendar_and_membership_drift():
    from investment_os.application.weekly_review import eligible_weekly_periods
    consent = command()
    base = dict(
        authorization=consent, now=datetime(2026, 11, 16, tzinfo=UTC),
        enabled=True, revoked=False,
        persisted_watchlist_members=consent.watchlist_instrument_ids,
        calendar_coverage_attested=True, calendar_sessions=(date(2026, 11, 9),),
    )
    with pytest.raises(WeeklyReviewError, match="WEEKLY_CALENDAR_CHANGED"):
        eligible_weekly_periods(
            **base, persisted_calendar_import_id=uuid4(),
            persisted_members=consent.portfolio_instrument_ids,
        )
    with pytest.raises(WeeklyReviewError, match="WEEKLY_PORTFOLIO_MEMBERSHIP_CHANGED"):
        eligible_weekly_periods(
            **base, persisted_calendar_import_id=consent.calendar_import_id,
            persisted_members=(uuid4(),),
        )
    with pytest.raises(WeeklyReviewError, match="WEEKLY_DUPLICATE_CALENDAR_SESSION"):
        eligible_weekly_periods(
            **(base | {"calendar_sessions": (date(2026, 11, 9),) * 2}),
            persisted_calendar_import_id=consent.calendar_import_id,
            persisted_members=consent.portfolio_instrument_ids,
        )


def test_weekly_worker_preflight_expires_at_exact_boundary():
    from investment_os.application.weekly_review import eligible_weekly_periods
    consent = command()
    assert eligible_weekly_periods(
        consent, datetime(2026, 12, 1, tzinfo=UTC),
        enabled=True, revoked=False,
        persisted_calendar_import_id=consent.calendar_import_id,
        persisted_members=consent.portfolio_instrument_ids,
        persisted_watchlist_members=consent.watchlist_instrument_ids,
        calendar_coverage_attested=True,
        calendar_sessions=(),
    ) == ()


def test_weekly_worker_preflight_requires_attested_complete_calendar():
    from investment_os.application.weekly_review import eligible_weekly_periods
    consent = command()
    with pytest.raises(WeeklyReviewError, match="WEEKLY_CALENDAR_COVERAGE_NOT_ATTESTED"):
        eligible_weekly_periods(
            consent, datetime(2026, 11, 16, tzinfo=UTC), enabled=True, revoked=False,
            persisted_calendar_import_id=consent.calendar_import_id,
            persisted_members=consent.portfolio_instrument_ids,
            persisted_watchlist_members=consent.watchlist_instrument_ids,
            calendar_sessions=(date(2026, 11, 9),),
            calendar_coverage_attested=False,
        )


def test_weekly_worker_preflight_rejects_watchlist_drift_and_duplicates():
    from investment_os.application.weekly_review import eligible_weekly_periods
    consent = command()
    base = dict(
        authorization=consent, now=datetime(2026, 11, 16, tzinfo=UTC),
        enabled=True, revoked=False,
        persisted_calendar_import_id=consent.calendar_import_id,
        persisted_members=consent.portfolio_instrument_ids,
        calendar_sessions=(date(2026, 11, 9),),
        calendar_coverage_attested=True,
    )
    for members in ((uuid4(),), consent.watchlist_instrument_ids * 2):
        with pytest.raises(WeeklyReviewError, match="WEEKLY_WATCHLIST_MEMBERSHIP_CHANGED"):
            eligible_weekly_periods(**base, persisted_watchlist_members=members)


def test_weekly_report_freezes_source_linked_current_facts_and_explicit_unknowns():
    from decimal import Decimal
    from investment_os.application.weekly_review import (
        WeeklyLocalObservation, build_weekly_local_report,
    )
    shared = uuid4()
    missing = uuid4()
    consent = command(
        portfolio_instrument_ids=[shared],
        watchlist_instrument_ids=[shared, missing],
    )
    evidence = uuid4()
    report = build_weekly_local_report(
        consent, week_start=date(2026, 11, 9), week_end=date(2026, 11, 15),
        knowledge_as_of=datetime(2026, 11, 16, tzinfo=UTC),
        observations=(WeeklyLocalObservation(
            shared, evidence, datetime(2026, 11, 13, tzinfo=UTC),
            Decimal("12.34"), datetime(2026, 11, 13, tzinfo=UTC),
        ),),
    )
    assert report.historical_holdings_status == "NOT_PROVIDED"
    assert len(report.rows) == 2
    rows = {row.instrument_id: row for row in report.rows}
    assert rows[shared].membership == ("PORTFOLIO", "WATCHLIST")
    assert rows[shared].last_known_price == Decimal("12.34")
    assert rows[shared].evidence_id == evidence
    assert rows[shared].historical_return_status == "NOT_PROVIDED"
    assert rows[missing].price_status == "UNKNOWN"
    assert rows[missing].last_known_price is None
    assert rows[missing].evidence_id is None
    assert rows[shared].observed_at == datetime(2026, 11, 13, tzinfo=UTC)


def test_weekly_report_missing_provenance_never_exposes_unverified_price():
    from decimal import Decimal
    from investment_os.application.weekly_review import (
        WeeklyLocalObservation, build_weekly_local_report,
    )
    consent = command()
    report = build_weekly_local_report(
        consent, week_start=date(2026, 11, 9), week_end=date(2026, 11, 15),
        knowledge_as_of=datetime(2026, 11, 16, tzinfo=UTC),
        observations=(WeeklyLocalObservation(
            consent.portfolio_instrument_ids[0], None,
            datetime(2026, 11, 13, tzinfo=UTC), Decimal("10"),
        ),),
    )
    row = next(row for row in report.rows if row.instrument_id == consent.portfolio_instrument_ids[0])
    assert row.price_status == "UNKNOWN"
    assert row.last_known_price is None


@pytest.mark.parametrize("case", [
    "not_closed", "outside_scope", "unauthorized", "duplicate",
    "future", "naive", "zero", "nan",
])
def test_weekly_report_rejects_invalid_period_sources_and_prices(case):
    from decimal import Decimal
    from investment_os.application.weekly_review import (
        WeeklyLocalObservation, build_weekly_local_report,
    )
    consent = command()
    now = datetime(2026, 11, 16, tzinfo=UTC)
    instrument = consent.portfolio_instrument_ids[0]
    item = WeeklyLocalObservation(instrument, uuid4(), now, Decimal("10"))
    observations = (item,)
    week_start, week_end = date(2026, 11, 9), date(2026, 11, 15)
    if case == "not_closed":
        now = datetime(2026, 11, 15, 15, tzinfo=UTC)
    elif case == "outside_scope":
        week_start, week_end = date(2026, 11, 2), date(2026, 11, 8)
    elif case == "unauthorized":
        observations = (WeeklyLocalObservation(uuid4(), uuid4(), now, Decimal("10")),)
    elif case == "duplicate":
        observations = (item, item)
    elif case == "future":
        observations = (WeeklyLocalObservation(instrument, uuid4(), datetime(2026, 11, 17, tzinfo=UTC), Decimal("10")),)
    elif case == "naive":
        observations = (WeeklyLocalObservation(instrument, uuid4(), datetime(2026, 11, 13), Decimal("10")),)
    elif case == "zero":
        observations = (WeeklyLocalObservation(instrument, uuid4(), now, Decimal("0")),)
    elif case == "nan":
        observations = (WeeklyLocalObservation(instrument, uuid4(), now, Decimal("NaN")),)
    with pytest.raises(WeeklyReviewError, match="WEEKLY_REPORT_"):
        build_weekly_local_report(
            consent, week_start=week_start, week_end=week_end,
            knowledge_as_of=now, observations=observations,
        )


def test_weekly_report_evidence_without_available_at_is_not_source_linked():
    from decimal import Decimal
    from investment_os.application.weekly_review import WeeklyLocalObservation, build_weekly_local_report
    consent = command()
    report = build_weekly_local_report(
        consent, week_start=date(2026, 11, 9), week_end=date(2026, 11, 15),
        knowledge_as_of=datetime(2026, 11, 16, tzinfo=UTC),
        observations=(WeeklyLocalObservation(
            consent.portfolio_instrument_ids[0], uuid4(),
            datetime(2026, 11, 13, tzinfo=UTC), Decimal("10"),
        ),),
    )
    row = next(row for row in report.rows if row.instrument_id == consent.portfolio_instrument_ids[0])
    assert row.price_status == "UNKNOWN"
    assert row.last_known_price is None
    assert row.evidence_id is None


@pytest.mark.parametrize("availability", [
    datetime(2026, 11, 17, tzinfo=UTC), datetime(2026, 11, 13),
])
def test_weekly_report_rejects_future_or_naive_evidence_availability(availability):
    from decimal import Decimal
    from investment_os.application.weekly_review import WeeklyLocalObservation, build_weekly_local_report
    consent = command()
    with pytest.raises(WeeklyReviewError, match="WEEKLY_REPORT_INVALID_AVAILABILITY_TIME"):
        build_weekly_local_report(
            consent, week_start=date(2026, 11, 9), week_end=date(2026, 11, 15),
            knowledge_as_of=datetime(2026, 11, 16, tzinfo=UTC),
            observations=(WeeklyLocalObservation(
                consent.portfolio_instrument_ids[0], uuid4(),
                datetime(2026, 11, 13, tzinfo=UTC), Decimal("10"), availability,
            ),),
        )
