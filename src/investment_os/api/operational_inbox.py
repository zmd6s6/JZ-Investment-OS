"""Read-only operational inbox. Each persisted source fails independently."""
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from fastapi import APIRouter

from investment_os.application.decision_center import DecisionCenterPort
from investment_os.application.daily_runtime import DailyRuntimeService
from investment_os.application.monthly_review import MonthlyReviewPort


class InboxItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_id: UUID
    source: Literal["DECISION", "DAILY_TASK", "MONTHLY_TASK"]
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
    return InboxSection(state="NOT_PROVIDED", message="暂无可核实的独立投资判断来源，未提供。")


def _section(items: list[InboxItem], *, limited: bool) -> InboxSection:
    return InboxSection(
        state="AVAILABLE" if items else "EMPTY",
        items=tuple(items[:LIMIT]),
        limited=limited,
        message="仅显示最多20条匹配记录，不代表全部数量。" if limited else
                ("没有符合条件的持久化记录。" if not items else "来自本地持久化记录。"),
    )


async def pending(center: DecisionCenterPort | None, now: datetime) -> InboxSection:
    if center is None:
        return InboxSection(state="ERROR", message="决策来源不可用，请到决策中心核对。")
    try:
        cards = await center.list()
        # Card state alone cannot prove eligibility: require current detail, expiry and
        # allowed actions. Fail closed on any malformed/inaccessible candidate.
        items: list[InboxItem] = []
        for card in cards:
            if card.state != "PENDING_APPROVAL":
                continue
            detail = await center.get(card.decision_id)
            if (
                detail.decision.state != "PENDING_APPROVAL"
                or "APPROVE" not in detail.allowed_actions
                or (detail.approval_expires_at is not None and detail.approval_expires_at <= now)
                or detail.lineage.get("risk_veto") is not False
            ):
                continue
            items.append(InboxItem(
                source_id=card.decision_id, source="DECISION",
                status="PENDING_APPROVAL", observed_at=card.created_at,
                detail_url="/decisions", description=f"{card.symbol} · {card.action} · 待人工审阅",
            ))
        items.sort(key=lambda x: (x.observed_at, str(x.source_id)), reverse=True)
        return _section(items, limited=len(items) > LIMIT)
    except Exception:
        return InboxSection(state="ERROR", message="读取或校验决策失败；未将未知状态显示为可审批。")


async def degraded(
    daily: DailyRuntimeService | None, monthly: MonthlyReviewPort | None,
) -> InboxSection:
    if daily is None and monthly is None:
        return InboxSection(state="ERROR", message="运行历史来源未装配。")
    items: list[InboxItem] = []
    failures: list[str] = []
    for label, service in (("DAILY_TASK", daily), ("MONTHLY_TASK", monthly)):
        if service is None:
            failures.append(label)
            continue
        try:
            runs = await (service.store.runs() if label == "DAILY_TASK" else service.runs(0))
            for run in runs:
                if run.status.upper() in {"FAILED", "DEGRADED", "ERROR", "CANCELLED"} or run.error_code:
                    items.append(InboxItem(
                        source_id=run.task_run_id, source=label,
                        status=run.status, observed_at=run.finished_at or run.started_at,
                        detail_url="/calendar",
                        description=f"{label} · {run.status} · {run.error_code or '请查看运行详情'}",
                    ))
        except Exception:
            failures.append(label)
    items.sort(key=lambda x: (x.observed_at, str(x.source_id)), reverse=True)
    if failures:
        return InboxSection(
            state="ERROR", items=tuple(items[:LIMIT]), limited=len(items) > LIMIT,
            message="部分运行来源不可用：" + ", ".join(failures) + "；其余记录仍可查看。",
        )
    return _section(items, limited=len(items) > LIMIT)


def operational_inbox_router(
    center: DecisionCenterPort | None,
    daily: DailyRuntimeService | None,
    monthly: MonthlyReviewPort | None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/operational-inbox", tags=["operational-inbox"])

    @router.get("", response_model=OperationalInbox)
    async def read_inbox() -> OperationalInbox:
        now = datetime.now(UTC)
        return OperationalInbox(
            as_of=now,
            pending_approvals=await pending(center, now),
            degraded_runs=await degraded(daily, monthly),
            action_required=unsupported(),
            hold_watch=unsupported(),
            new_opportunity=unsupported(),
            risk_veto=unsupported(),
        )

    return router
