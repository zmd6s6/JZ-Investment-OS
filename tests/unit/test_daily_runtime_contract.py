"""Explicit scope/cost/time boundaries, not grants inferred from a calendar toggle."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from investment_os.application.analysis_runs import ANALYSIS_ROLES
from investment_os.application.daily_runtime import (
    DailyConfiguration,
    DailyDraft,
    DailyEvidence,
    DailyLimits,
    DailyMember,
    DailyMode,
    DailyPrepared,
    DailySave,
    assert_authorized,
    evidence_diff,
)

NOW = datetime(2026, 11, 2, 8, tzinfo=UTC)


def draft():
    return dict(
        name="合成每日检查",
        mode="LOCAL_STATUS_ONLY",
        market="SSE",
        portfolio_id=uuid4(),
        portfolio_instrument_ids=(uuid4(),),
        watchlist_instrument_ids=(),
        calendar_import_id=uuid4(),
        coverage_start=date(2026, 11, 2),
        coverage_end=date(2026, 11, 6),
        frequency="DAILY_AFTER_EXPLICIT_CLOSE",
        missed_run_policy="LOCAL_REPORT_ONLY_NO_RESEARCH",
        quote_source_name="合成本地报价",
        evidence_source_names=(),
        retention_days=7,
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=8),
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


def test_local_daily_permission_requires_explicit_empty_profiles_and_zero_costs():
    command = DailyDraft(**draft())
    assert command.instrument_ids == command.portfolio_instrument_ids
    assert command.model_profiles == {} and command.data_profile_ids == ()
    for patch in [
        dict(model_profiles={ANALYSIS_ROLES[0]: uuid4()}),
        dict(model_egress_acknowledgement=True),
        dict(cost_acknowledgement=True),
        dict(local_only_acknowledgement=False),
    ]:
        with pytest.raises(ValidationError):
            DailyDraft(**{**draft(), **patch})


@pytest.mark.parametrize(
    "field",
    [
        "frequency",
        "retention_days",
        "valid_until",
        "pause_method",
        "scope_acknowledgement",
        "complete_calendar_acknowledgement",
        "limits",
        "data_profile_ids",
        "model_profiles",
        "portfolio_instrument_ids",
        "watchlist_instrument_ids",
    ],
)
def test_no_missing_authorization_field_is_inferred_from_status_only(field):
    value = draft()
    del value[field]
    with pytest.raises(ValidationError):
        DailyDraft(**value)


def test_shadow_requires_all_roles_and_cost_consent_but_never_unpriced_data_calls():
    value = {
        **draft(),
        "mode": "SCHEDULED_SHADOW",
        "evidence_source_names": ("合成资料",),
        "local_only_acknowledgement": False,
        "model_profiles": {role: uuid4() for role in ANALYSIS_ROLES},
        "model_egress_acknowledgement": True,
        "cost_acknowledgement": True,
        "limits": dict(
            currency="USD", task_tokens=1000, day_tokens=2000, task_cost="1", day_cost="2"
        ),
    }
    assert DailyDraft(**value).mode == "SCHEDULED_SHADOW"
    for patch in [
        dict(model_profiles={}),
        dict(cost_acknowledgement=False),
        dict(model_egress_acknowledgement=False),
        dict(data_profile_ids=(uuid4(),)),
    ]:
        with pytest.raises(ValidationError):
            DailyDraft(**{**value, **patch})


@pytest.mark.parametrize(
    "patch",
    [
        {"portfolio_instrument_ids": (), "watchlist_instrument_ids": ()},
        {"portfolio_instrument_ids": tuple(uuid4() for _ in range(101))},
        {"coverage_end": date(2026, 11, 1)},
        {"coverage_end": date(2028, 1, 1)},
        {"valid_until": NOW - timedelta(days=2)},
        {"retention_days": True},
        {"scope_acknowledgement": 1},
        {"complete_calendar_acknowledgement": 1},
        {"local_only_acknowledgement": 1},
        {"frequency": "WEEKDAYS"},
        {"auto_trade": True},
    ],
)
def test_daily_scope_date_type_and_governance_boundaries_fail_closed(patch):
    with pytest.raises(ValidationError):
        DailyDraft(**{**draft(), **patch})


def test_scope_union_is_exact_not_silently_duplicated_or_expanded():
    a, b = uuid4(), uuid4()
    command = DailyDraft(
        **{**draft(), "portfolio_instrument_ids": (a,), "watchlist_instrument_ids": (a, b)}
    )
    assert set(command.instrument_ids) == {a, b}
    with pytest.raises(ValidationError):
        DailyDraft(**{**draft(), "portfolio_instrument_ids": (a, a)})
    with pytest.raises(ValidationError):
        DailyLimits(currency="USD", task_tokens=3, day_tokens=2, task_cost="1", day_cost="2")
    with pytest.raises(ValidationError):
        DailyLimits(currency="USD", task_tokens=1, day_tokens=2, task_cost=1.2, day_cost="2")


def row(**patch):
    return DailyEvidence(
        evidence_id=uuid4(),
        instrument_id=uuid4(),
        source_name="synthetic",
        content_hash="a" * 64,
        observed_at=NOW - timedelta(days=1),
        effective_at=NOW - timedelta(days=1),
        available_at=NOW - timedelta(hours=1),
        ingested_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(days=1),
        quality_score="1",
        **patch,
    )


def test_first_daily_diff_is_not_a_fabricated_prior_baseline():
    evidence = row()
    result = evidence_diff((evidence,), as_of=NOW, previous=(), baseline_report_id=None)
    assert result.baseline_status == "FIRST_RUN_NO_BASELINE"
    assert result.visible_ids == result.added_ids == (evidence.evidence_id,)
    assert result.removed_ids == ()


@pytest.mark.parametrize("field", ["observed_at", "effective_at", "available_at", "ingested_at"])
def test_all_four_business_times_exclude_future_or_late_evidence(field):
    evidence = row().model_copy(update={field: NOW + timedelta(seconds=1)})
    result = evidence_diff(
        (evidence,), as_of=NOW, previous=(evidence.evidence_id,), baseline_report_id=uuid4()
    )
    assert result.visible_ids == result.added_ids == ()
    assert result.removed_ids == (evidence.evidence_id,)
    assert result.excluded[evidence.evidence_id] == "FUTURE_OR_LATE_INGESTED"


def test_expiry_at_exact_business_time_is_excluded_and_diff_replay_is_deterministic():
    expired = row().model_copy(update={"expires_at": NOW})
    fresh = row()
    identifier = uuid4()
    first = evidence_diff(
        (expired, fresh), as_of=NOW, previous=(expired.evidence_id,), baseline_report_id=identifier
    )
    assert first.excluded == {expired.evidence_id: "EXPIRED"}
    assert first.removed_ids == (expired.evidence_id,) and first.added_ids == (fresh.evidence_id,)
    assert first == evidence_diff(
        (fresh, expired), as_of=NOW, previous=(expired.evidence_id,), baseline_report_id=identifier
    )
    with pytest.raises(ValueError, match="DAILY_EVIDENCE_IDENTITY_CONFLICT"):
        evidence_diff((fresh, fresh), as_of=NOW, previous=(), baseline_report_id=None)


@pytest.mark.parametrize(
    "patch,code",
    [
        ({"revoked": True}, "DAILY_AUTHORIZATION_REVOKED"),
        ({"enabled": False}, "DAILY_PAUSED"),
        ({"version": 3}, "DAILY_VERSION_CHANGED"),
    ],
)
def test_authorization_latest_version_pause_and_revoke_are_not_optional(patch, code):
    command = DailySave(**draft(), request_id=uuid4(), schedule_id=uuid4(), expected_version=0)
    prepared = DailyPrepared(
        command=command,
        calendar_hash="a" * 64,
        calendar_source="synthetic",
        calendar_version="v1",
        members=(
            DailyMember(
                instrument_id=command.instrument_ids[0],
                market="SSE",
                symbol="SYN",
                name="合成",
                in_portfolio=True,
                in_watchlist=False,
            ),
        ),
        models={},
        model_pricing={},
        data_profiles=(),
        budget_hash=None,
        budget_snapshot=None,
        prepared_at=NOW,
        input_hash="b" * 64,
    )
    config = DailyConfiguration(
        schedule_id=command.schedule_id,
        revision_id=uuid4(),
        version=2,
        enabled=True,
        revoked=False,
        enabled_since=NOW,
        prepared=prepared,
    )
    assert_authorized(config, version=2, now=NOW)
    with pytest.raises(ValueError, match=code):
        assert_authorized(config.model_copy(update=patch), version=2, now=NOW)
    with pytest.raises(ValueError, match="DAILY_AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID"):
        assert_authorized(config, version=2, now=NOW + timedelta(days=9))
    with pytest.raises(ValidationError):
        DailyMode(request_id=uuid4(), expected_version=2, action="ENABLE", confirmed=1)


@pytest.mark.parametrize("quality", ["NaN", "Infinity", "bad", "-0.1", "1.1"])
def test_invalid_evidence_quality_never_becomes_a_fresh_fact(quality):
    evidence = row().model_copy(update={"quality_score": quality})
    result = evidence_diff((evidence,), as_of=NOW, previous=(), baseline_report_id=None)
    assert result.visible_ids == ()
    assert result.excluded == {evidence.evidence_id: "INVALID_QUALITY"}
