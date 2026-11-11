"""Read-only operational inbox. Each persisted source fails independently."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from investment_os.application.daily_runtime import DailyRuntimeService, DailyTask
from investment_os.application.decision_center import DecisionCenterPort
from investment_os.application.monthly_review import MonthlyReviewPort


class InboxItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_id: UUID
    source: Literal["DECISION", "DAILY_TASK", "MONTHLY_TASK", "DAILY_REPORT"]
    status: str
    observed_at: datetime
    detail_url: str
    description: str


class InboxSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    state: Literal["AVAILABLE", "EMPTY", "ERROR", "NOT_PROVIDED"]
    items: tuple[InboxItem, ...] = ()
    limited: bool = False
    message: str


class OperationalInbox(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    as_of: datetime
    pending_approvals: InboxSection
    degraded_runs: InboxSection
    action_required: InboxSection
    hold_watch: InboxSection
    new_opportunity: InboxSection
    risk_veto: InboxSection
    auto_trade: Literal[False] = False


LIMIT = 20


def unsupported() -> InboxSection:
    return InboxSection(state="NOT_PROVIDED", message="暂无可核实的独立投资判断来源, 未提供。")


def _section(items: list[InboxItem], *, limited: bool) -> InboxSection:
    return InboxSection(
        state="AVAILABLE" if items else "EMPTY",
        items=tuple(items[:LIMIT]),
        limited=limited,
        message=(
            "仅读取最近决策100条、日报100条、每日任务100条和月度任务60条. "
            "最多展示20条匹配记录, 窗口外尚未核对。"
        )
        if limited
        else ("没有符合条件的持久化记录。" if not items else "来自本地持久化记录。"),
    )


async def pending(center: DecisionCenterPort | None, now: datetime) -> InboxSection:
    if center is None:
        return InboxSection(state="ERROR", message="决策来源不可用, 请到决策中心核对。")
    try:
        cards = await center.list()
        # Card state alone cannot prove eligibility: require current detail, expiry and
        # allowed actions. Fail closed on any malformed/inaccessible candidate.
        items: list[InboxItem] = []
        for card in cards[:100]:
            if card.state != "PENDING_APPROVAL":
                continue
            detail = await center.get(card.decision_id)
            if (
                detail.decision.state != "PENDING_APPROVAL"
                or "APPROVE" not in detail.allowed_actions
                or (detail.approval_expires_at is not None and detail.approval_expires_at <= now)
                or bool(detail.decision.blockers)
            ):
                continue
            items.append(
                InboxItem(
                    source_id=card.decision_id,
                    source="DECISION",
                    status="PENDING_APPROVAL",
                    observed_at=card.created_at,
                    detail_url=f"/decisions?decision_id={card.decision_id}",
                    description=f"{card.symbol} · {card.action} · 待人工审阅",
                )
            )
        items.sort(key=lambda x: (x.observed_at, str(x.source_id)), reverse=True)
        return _section(items, limited=len(items) > LIMIT or len(cards) >= 100)
    except Exception:
        return InboxSection(state="ERROR", message="读取或校验决策失败. 未将未知状态显示为可审批。")


async def degraded(
    daily: DailyRuntimeService | None,
    monthly: MonthlyReviewPort | None,
) -> InboxSection:
    if daily is None and monthly is None:
        return InboxSection(state="ERROR", message="运行历史来源未装配。")
    items: list[InboxItem] = []
    failures: list[str] = []
    window_limited = False
    readers: tuple[
        tuple[
            Literal["DAILY_TASK", "MONTHLY_TASK"],
            Callable[[], Awaitable[tuple[DailyTask, ...]]] | None,
        ],
        ...,
    ] = (
        ("DAILY_TASK", daily.store.runs if daily else None),
        ("MONTHLY_TASK", monthly.runs if monthly else None),
    )
    for label, read_runs in readers:
        if read_runs is None:
            failures.append(label)
            continue
        try:
            runs = await asyncio.wait_for(read_runs(), timeout=2)
            window_limited = window_limited or len(runs) >= (100 if label == "DAILY_TASK" else 60)
            for run in runs[: 100 if label == "DAILY_TASK" else 60]:
                if (
                    run.status.upper() in {"FAILED", "DEGRADED", "ERROR", "CANCELLED"}
                    or run.error_code
                ):
                    items.append(
                        InboxItem(
                            source_id=run.task_run_id,
                            source=label,
                            status=run.status,
                            observed_at=run.finished_at or run.started_at,
                            detail_url=(f"/calendar#{label.lower()}-{run.task_run_id}"),
                            description=(
                                f"{label} · {run.status} · {run.error_code or '请查看运行详情'}"
                            ),
                        )
                    )
        except Exception:
            failures.append(label)
    if daily is not None:
        try:
            reports = await asyncio.wait_for(daily.store.reports(), timeout=2)
            window_limited = window_limited or len(reports) >= 100
            for report in reports[:100]:
                if (
                    report.phase == "DEGRADED"
                    or report.data_job_degraded.availability == "DEGRADED"
                ):
                    items.append(
                        InboxItem(
                            source_id=report.report_id,
                            source="DAILY_REPORT",
                            status=report.phase,
                            observed_at=report.recorded_at,
                            detail_url=f"/calendar#daily_report-{report.report_id}",
                            description="日报记录了降级状态, 请核对原报告。",
                        )
                    )
        except Exception:
            failures.append("DAILY_REPORT")
    items.sort(key=lambda x: (x.observed_at, str(x.source_id)), reverse=True)
    if failures:
        return InboxSection(
            state="ERROR",
            items=tuple(items[:LIMIT]),
            limited=len(items) > LIMIT or window_limited,
            message="部分运行来源不可用: " + ", ".join(failures) + ". 其余记录仍可查看。",
        )
    return _section(items, limited=len(items) > LIMIT or window_limited)


class OperationalInboxService:
    def __init__(
        self,
        center: DecisionCenterPort | None,
        daily: DailyRuntimeService | None,
        monthly: MonthlyReviewPort | None,
    ):
        self.center, self.daily, self.monthly = center, daily, monthly

    async def read(self) -> OperationalInbox:
        now = datetime.now(UTC)
        return OperationalInbox(
            as_of=now,
            pending_approvals=await self._pending(now),
            degraded_runs=await self._degraded(),
            action_required=unsupported(),
            hold_watch=unsupported(),
            new_opportunity=unsupported(),
            risk_veto=unsupported(),
        )

    async def _pending(self, now: datetime) -> InboxSection:
        try:
            return await asyncio.wait_for(pending(self.center, now), timeout=5)
        except TimeoutError:
            return InboxSection(state="ERROR", message="读取决策超时, 请刷新核对。")

    async def _degraded(self) -> InboxSection:
        try:
            return await asyncio.wait_for(degraded(self.daily, self.monthly), timeout=8)
        except TimeoutError:
            return InboxSection(state="ERROR", message="读取运行历史超时, 请刷新核对。")
