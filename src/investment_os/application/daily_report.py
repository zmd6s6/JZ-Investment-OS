"""Render honest typed daily sections from immutable local input and real analysis views."""

from datetime import date, datetime
from uuid import UUID

from investment_os.application.analysis_runs import AnalysisRunView
from investment_os.application.daily_runtime import (
    DailyConfiguration,
    DailyError,
    DailyEvidenceDiff,
    DailyLocalInputs,
    DailyReport,
    DailySection,
)
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.application.schedule import MarketVenue
from investment_os.domain.analysis_run import TERMINAL_ANALYSIS


def section(message: str) -> DailySection:
    return DailySection(availability="NOT_PROVIDED", messages=(message,))


def build_daily_report(
    *,
    report_id: UUID,
    task_run_id: UUID,
    config: DailyConfiguration,
    business_date: date,
    business_as_of: datetime,
    as_of: datetime,
    recorded_at: datetime,
    local: DailyLocalInputs,
    diff: DailyEvidenceDiff,
    planned_count: int,
    analyses: tuple[AnalysisRunView, ...] = (),
) -> DailyReport:
    prepared = config.prepared
    command = prepared.command
    if (
        business_as_of.utcoffset() is None
        or business_as_of.astimezone(MarketVenue(command.market).timezone).date() != business_date
    ):
        raise DailyError("DAILY_BUSINESS_DATE_MISMATCH")
    if not 0 <= planned_count <= len(command.instrument_ids):
        raise DailyError("DAILY_ANALYSIS_PLAN_OUTSIDE_SCOPE")
    missed = as_of.astimezone(MarketVenue(command.market).timezone).date() != business_date
    if missed and planned_count:
        raise DailyError("DAILY_MISSED_SESSION_RESEARCH_FORBIDDEN")
    if (
        local.content_hash != fingerprint(local.model_dump(mode="json", exclude={"content_hash"}))
        or local.members != prepared.members
        or local.portfolio.portfolio_id != command.portfolio_id
        or {position.instrument_id for position in local.portfolio.positions}
        != set(command.portfolio_instrument_ids)
    ):
        raise DailyError("DAILY_LOCAL_SNAPSHOT_INVALID")
    if (
        set(local.quote_statuses) != set(command.instrument_ids)
        or any(
            row.instrument_id not in command.instrument_ids
            or row.source_name
            not in set(command.evidence_source_names) | {command.quote_source_name}
            for row in local.evidence
        )
        or set(diff.visible_ids)
        != {row.evidence_id for row in local.evidence if row.reason(as_of) is None}
    ):
        raise DailyError("DAILY_LOCAL_SOURCE_OR_EVIDENCE_SCOPE_INVALID")
    if (
        len({run.run_id for run in analyses}) != len(analyses)
        or len(analyses) > planned_count
        or any(
            run.instrument_id not in command.instrument_ids
            or run.portfolio_id != command.portfolio_id
            for run in analyses
        )
    ):
        raise DailyError("DAILY_ANALYSIS_REFERENCE_OUTSIDE_SCOPE")
    if command.mode == "LOCAL_STATUS_ONLY" and (analyses or planned_count):
        raise DailyError("DAILY_LOCAL_ANALYSIS_REFERENCE_FORBIDDEN")
    missing = tuple(
        str(identifier)
        for identifier, status in local.quote_statuses.items()
        if status != "AVAILABLE"
    )
    degraded = []
    if missed:
        degraded.append("错过原业务日, 仅记录当前本地状态; 不补发历史定时模型费用或伪造历史持仓。")
    if missing:
        degraded.append(f"业务时点缺少可用本地报价: {len(missing)}项; 没有借旧价或外部补价。")
    if diff.excluded:
        degraded.append(
            f"未来、后到、过期或质量无效资料排除{len(diff.excluded)}项; 不作为本次事实。"
        )
    if not diff.visible_ids:
        degraded.append("本次明确来源和时点没有有效本地Evidence; 未自动调用外部资料。")
    pending = planned_count > len(analyses) or any(
        run.status not in TERMINAL_ANALYSIS for run in analyses
    )
    if command.mode == "SCHEDULED_SHADOW" and planned_count == 0:
        degraded.append("没有可安全排入的影子分析; 未自动扩大标的、来源或费用。")
    for run in analyses:
        if run.status.value in {"FAILED", "CANCELLED", "DEGRADED"}:
            degraded.append(
                f"分析{run.run_id}: {run.status.value}; "
                f"{run.error_code or '打开分析查看实际缺项'}。"
            )
    phase = (
        "SHADOW_PENDING"
        if command.mode == "SCHEDULED_SHADOW" and pending
        else (
            "DEGRADED"
            if degraded
            else "LOCAL_COMPLETE"
            if command.mode == "LOCAL_STATUS_ONLY"
            else "SHADOW_COMPLETE"
        )
    )
    run_ids = tuple(run.run_id for run in analyses)
    vetoes = tuple(
        run
        for run in analyses
        if run.shadow_decision is not None and run.shadow_decision.risk_gate == "VETO"
    )
    shadows = tuple(run for run in analyses if run.shadow_decision is not None)
    return DailyReport(
        report_id=report_id,
        task_run_id=task_run_id,
        schedule_id=config.schedule_id,
        revision_id=config.revision_id,
        authorization_version=config.version,
        business_date=business_date,
        business_as_of=business_as_of,
        as_of=as_of,
        recorded_at=recorded_at,
        phase=phase,
        mode=command.mode,
        scope_hash=prepared.input_hash,
        authorization=prepared,
        local_inputs=local,
        evidence_diff=diff,
        action_required=DailySection(
            availability="DEGRADED" if degraded else "NOT_PROVIDED",
            messages=tuple(degraded)
            if degraded
            else ("本日报未提供可审批投资Action; 不会自动批准或记录执行。",),
            analysis_run_ids=run_ids,
        ),
        hold_watch=DailySection(
            availability="PROVIDED" if shadows else "NOT_PROVIDED",
            messages=tuple(
                f"影子分析{run.run_id}: {run.shadow_decision.action.value}; 非可执行建议。"
                for run in shadows
                if run.shadow_decision
            )
            or (
                f"范围含{len(command.portfolio_instrument_ids)}项登记持仓、"
                f"{len(command.watchlist_instrument_ids)}项明确观察标的; 继续持有判断未提供。",
            ),
            analysis_run_ids=tuple(run.run_id for run in shadows),
        ),
        new_opportunity=section(
            "本每日任务未提供机会漏斗或新机会判断; 没有全市场扫描或强模型扇出。"
        ),
        risk_veto=DailySection(
            availability="PROVIDED" if vetoes else "NOT_PROVIDED",
            messages=tuple(
                f"分析{run.run_id}记录Risk Veto, 禁止增加风险; 打开原始分析核对证据。"
                for run in vetoes
            )
            or ("本日报未提供可核对Risk Veto汇总; 不能解释为Risk PASS。",),
            analysis_run_ids=tuple(run.run_id for run in vetoes),
        ),
        approvals=section("本日报未提供待处理审批汇总; 没有创建、批准或记录执行。"),
        data_job_degraded=DailySection(
            availability="DEGRADED" if degraded else "PROVIDED",
            messages=tuple(degraded)
            or (
                (
                    "本地检查已持久完成; 真实影子分析仍待Worker终态。"
                    if pending
                    else "本地读取与实际任务状态已记录; 不保证外部提供方健康。"
                ),
            ),
            evidence_ids=tuple(diff.excluded),
            analysis_run_ids=run_ids,
        ),
    )
