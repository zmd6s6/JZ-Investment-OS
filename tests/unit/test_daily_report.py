"""Daily sections are honest about missing inputs and actual linked analysis state."""

from uuid import uuid4

import pytest
from test_daily_runtime_contract import NOW, draft, row

from investment_os.application.daily_report import build_daily_report
from investment_os.application.daily_runtime import (
    DailyConfiguration,
    DailyLocalInputs,
    DailyMember,
    DailyPortfolioSnapshot,
    DailyPosition,
    DailyPrepared,
    DailySave,
    evidence_diff,
)
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.domain.analysis_run import AnalysisStatus


def fixture():
    command = DailySave(**draft(), request_id=uuid4(), schedule_id=uuid4(), expected_version=0)
    member = DailyMember(
        instrument_id=command.instrument_ids[0],
        market="SSE",
        symbol="SYN",
        name="合成标的",
        in_portfolio=True,
        in_watchlist=False,
    )
    prepared = DailyPrepared(
        command=command,
        calendar_hash="a" * 64,
        calendar_source="synthetic",
        calendar_version="v1",
        members=(member,),
        models={},
        model_pricing={},
        data_profiles=(),
        budget_hash=None,
        budget_snapshot=None,
        prepared_at=NOW,
        input_hash="0" * 64,
    )
    prepared = prepared.model_copy(
        update={"input_hash": fingerprint(prepared.model_dump(mode="json", exclude={"input_hash"}))}
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
    evidence = row().model_copy(
        update={"instrument_id": member.instrument_id, "source_name": command.quote_source_name}
    )
    portfolio = DailyPortfolioSnapshot(
        portfolio_id=command.portfolio_id,
        name="合成组合",
        base_currency="CNY",
        cash_balance="100",
        read_at=NOW,
        time_semantics="CURRENT_BOOK_READ_NOT_HISTORICAL_CLOSE_SNAPSHOT",
        positions=(
            DailyPosition(
                instrument_id=member.instrument_id,
                core_quantity="1",
                tactical_quantity="2",
                core_average_cost="10",
                tactical_average_cost="11",
                core_reason="合成Core理由",
                tactical_reason="合成Tactical理由",
                version=1,
            ),
        ),
    )
    local = DailyLocalInputs(
        read_at=NOW,
        portfolio_read_at=NOW,
        portfolio=portfolio,
        members=(member,),
        evidence=(evidence,),
        quote_statuses={member.instrument_id: "AVAILABLE"},
        quote_evidence_ids={member.instrument_id: evidence.evidence_id},
        content_hash="0" * 64,
    )
    local = seal(local)
    return config, local


def seal(local):
    return local.model_copy(
        update={
            "content_hash": fingerprint(local.model_dump(mode="json", exclude={"content_hash"}))
        }
    )


def report(config, local, **patch):
    arguments = dict(
        report_id=uuid4(),
        task_run_id=uuid4(),
        config=config,
        business_date=NOW.date(),
        business_as_of=NOW,
        as_of=NOW,
        recorded_at=NOW,
        local=local,
        diff=evidence_diff(local.evidence, as_of=NOW, previous=(), baseline_report_id=None),
        planned_count=0,
    )
    return build_daily_report(**{**arguments, **patch})


def test_local_report_shows_all_six_sections_and_never_invents_veto_approval_or_trade_action():
    config, local = fixture()
    result = report(config, local)
    assert result.phase == "LOCAL_COMPLETE" and result.auto_trade is False
    for field in [
        "action_required",
        "hold_watch",
        "new_opportunity",
        "risk_veto",
        "approvals",
        "data_job_degraded",
    ]:
        assert getattr(result, field).messages
    assert result.risk_veto.availability == result.approvals.availability == "NOT_PROVIDED"
    assert result.new_opportunity.availability == result.hold_watch.availability == "NOT_PROVIDED"
    assert "Risk PASS" in result.risk_veto.messages[0]
    assert (
        result.local_inputs.portfolio.time_semantics
        == "CURRENT_BOOK_READ_NOT_HISTORICAL_CLOSE_SNAPSHOT"
    )
    assert result.local_inputs.portfolio.positions[0].tactical_quantity == "2"


def test_missing_quotes_and_evidence_are_visible_degraded_not_a_successful_model_run():
    config, local = fixture()
    empty = seal(
        local.model_copy(
            update={
                "evidence": (),
                "quote_statuses": {local.members[0].instrument_id: "MISSING"},
                "quote_evidence_ids": {},
            }
        )
    )
    result = report(config, empty)
    assert result.phase == "DEGRADED" and result.data_job_degraded.availability == "DEGRADED"
    assert any("Evidence" in text for text in result.data_job_degraded.messages)
    assert result.hold_watch.analysis_run_ids == ()


def test_local_report_cannot_reference_a_model_run_or_fabricate_historical_scope():
    config, local = fixture()
    with pytest.raises(ValueError, match="DAILY_LOCAL_ANALYSIS_REFERENCE_FORBIDDEN"):
        report(config, local, planned_count=1)
    with pytest.raises(ValueError, match="DAILY_LOCAL_SNAPSHOT_INVALID"):
        report(config, local.model_copy(update={"content_hash": "f" * 64}))
    changed = seal(
        local.model_copy(
            update={"portfolio": local.portfolio.model_copy(update={"portfolio_id": uuid4()})}
        )
    )
    with pytest.raises(ValueError, match="DAILY_LOCAL_SNAPSHOT_INVALID"):
        report(config, changed)


async def shadow_fixture():
    from test_daily_profile_capture import fixture as profiles

    config, local = fixture()
    setup, _, command = profiles()
    command = command.model_copy(
        update={
            "portfolio_id": config.prepared.command.portfolio_id,
            "portfolio_instrument_ids": config.prepared.command.portfolio_instrument_ids,
            "watchlist_instrument_ids": (),
            "schedule_id": config.schedule_id,
            "quote_source_name": config.prepared.command.quote_source_name,
        }
    )
    models, pricing, budget, snapshot = await setup.capture_profiles(command, NOW)
    value = config.prepared.model_copy(
        update={
            "command": command,
            "models": models,
            "model_pricing": pricing,
            "budget_hash": budget,
            "budget_snapshot": snapshot,
        }
    )
    value = value.model_copy(
        update={"input_hash": fingerprint(value.model_dump(mode="json", exclude={"input_hash"}))}
    )
    return config.model_copy(update={"prepared": value}), local


def analysis(config, status="QUEUED", **patch):
    from investment_os.application.analysis_runs import AnalysisRunView

    return AnalysisRunView(
        run_id=uuid4(),
        request_id=uuid4(),
        portfolio_id=config.prepared.command.portfolio_id,
        instrument_id=config.prepared.command.instrument_ids[0],
        status=status,
        queued_at=NOW,
        started_at=None,
        finished_at=None,
        cancel_requested=False,
        retry_of=None,
        error_code=None,
        request_hash="a" * 64,
        input_hash=None,
        policy_version_id=None,
        **patch,
    )


async def test_shadow_dispatch_success_is_only_pending_until_actual_analysis_finishes():
    config, local = await shadow_fixture()
    queued = analysis(config)
    result = report(config, local, planned_count=1, analyses=(queued,))
    assert result.phase == "SHADOW_PENDING"
    assert result.hold_watch.availability == result.risk_veto.availability == "NOT_PROVIDED"
    failed = queued.model_copy(
        update={"status": AnalysisStatus.FAILED, "error_code": "ANALYSIS_EXECUTION_FAILED"}
    )
    result = report(config, local, planned_count=1, analyses=(failed,))
    assert result.phase == "DEGRADED"
    assert any("FAILED" in text for text in result.data_job_degraded.messages)
    assert result.data_job_degraded.analysis_run_ids == (failed.run_id,)


async def test_veto_field_requires_real_shadow_result_and_never_produces_approval():
    from investment_os.application.analysis_runs import ShadowDecision

    config, local = await shadow_fixture()
    shadow = ShadowDecision(
        action="AVOID",
        risk_intent="NONE",
        risk_gate="VETO",
        policy_version_id=None,
        thesis_version_id=None,
        reasons=({"text": "合成风险", "evidence_ids": (local.evidence[0].evidence_id,)},),
        blockers=("RISK_VETO",),
        input_hash="b" * 64,
    )
    run = analysis(config, status="DEGRADED", shadow_decision=shadow)
    result = report(config, local, planned_count=1, analyses=(run,))
    assert result.risk_veto.availability == result.hold_watch.availability == "PROVIDED"
    assert result.risk_veto.analysis_run_ids == (run.run_id,)
    assert result.approvals.availability == "NOT_PROVIDED" and result.auto_trade is False


def test_daily_report_rejects_wrong_date_missing_quote_states_and_outside_evidence():
    from datetime import timedelta

    config, local = fixture()
    with pytest.raises(ValueError, match="DAILY_BUSINESS_DATE_MISMATCH"):
        report(config, local, business_date=NOW.date() + timedelta(days=1))
    with pytest.raises(ValueError, match="DAILY_LOCAL_SOURCE_OR_EVIDENCE_SCOPE_INVALID"):
        report(config, seal(local.model_copy(update={"quote_statuses": {}})))
    bad = local.evidence[0].model_copy(update={"instrument_id": uuid4()})
    with pytest.raises(ValueError, match="DAILY_LOCAL_SOURCE_OR_EVIDENCE_SCOPE_INVALID"):
        report(config, seal(local.model_copy(update={"evidence": (bad,)})))


async def test_unrelated_analysis_or_plan_cannot_expand_daily_report_scope():
    config, local = await shadow_fixture()
    outside = analysis(config).model_copy(update={"portfolio_id": uuid4()})
    with pytest.raises(ValueError, match="DAILY_ANALYSIS_REFERENCE_OUTSIDE_SCOPE"):
        report(config, local, planned_count=1, analyses=(outside,))
    with pytest.raises(ValueError, match="DAILY_ANALYSIS_PLAN_OUTSIDE_SCOPE"):
        report(config, local, planned_count=101)


async def test_missed_business_day_is_local_only_and_never_replays_paid_research():
    from datetime import timedelta

    config, local = await shadow_fixture()
    missed = dict(
        business_date=NOW.date() - timedelta(days=1), business_as_of=NOW - timedelta(days=1)
    )
    result = report(config, local, **missed)
    assert result.phase == "DEGRADED"
    assert any("不补发历史" in text for text in result.data_job_degraded.messages)
    with pytest.raises(ValueError, match="DAILY_MISSED_SESSION_RESEARCH_FORBIDDEN"):
        report(config, local, planned_count=1, **missed)


def test_knowledge_time_is_separate_from_close_and_does_not_backdate_current_portfolio():
    from datetime import timedelta

    config, local = fixture()
    close = NOW - timedelta(minutes=10)
    result = report(config, local, business_as_of=close)
    assert result.business_as_of == close and result.as_of == NOW
    assert result.local_inputs.portfolio.read_at == NOW
    assert (
        result.local_inputs.portfolio.time_semantics
        == "CURRENT_BOOK_READ_NOT_HISTORICAL_CLOSE_SNAPSHOT"
    )
