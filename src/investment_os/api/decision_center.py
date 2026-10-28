"""Human actions only record immutable facts behind the standard write authentication."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException

from investment_os.application.decision_center import (
    CenterDetail,
    DecisionCard,
    DecisionCenterPort,
    HumanCommand,
    ManualExecutionCommand,
)
from investment_os.domain.errors import DomainError


def decision_center_router(center: DecisionCenterPort | None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/decision-center", tags=["decision-center"])

    def available() -> DecisionCenterPort:
        if center is None:
            raise HTTPException(503, detail={"code": "DECISION_CENTER_UNAVAILABLE"})
        return center

    @router.get("", response_model=tuple[DecisionCard, ...])
    async def list_decisions(portfolio_id: UUID | None = None) -> tuple[DecisionCard, ...]:
        return await available().list(portfolio_id=portfolio_id)

    @router.get("/{decision_id}", response_model=CenterDetail)
    async def detail(decision_id: UUID) -> CenterDetail:
        try:
            return await available().get(decision_id)
        except LookupError:
            raise HTTPException(404, detail={"code": "DECISION_NOT_FOUND"}) from None

    async def mutate(decision_id: UUID, action: str, command: HumanCommand) -> CenterDetail:
        assert action in {"APPROVE", "REJECT", "REVOKE", "RECORD_EXECUTION"}
        from typing import cast

        try:
            return await available().act(
                decision_id,
                cast(Literal["APPROVE", "REJECT", "REVOKE", "RECORD_EXECUTION"], action),
                command,
            )
        except LookupError:
            raise HTTPException(404, detail={"code": "DECISION_NOT_FOUND"}) from None
        except (ValueError, DomainError):
            raise HTTPException(
                409,
                detail={
                    "code": "DECISION_ACTION_BLOCKED",
                    "message": (
                        "未保存该操作: 状态、版本、批准或风险条件不符。请刷新核对; 不会提交订单。"
                    ),
                },
            ) from None

    @router.post("/{decision_id}/approve", response_model=CenterDetail)
    async def approve(decision_id: UUID, command: HumanCommand) -> CenterDetail:
        return await mutate(decision_id, "APPROVE", command)

    @router.post("/{decision_id}/reject", response_model=CenterDetail)
    async def reject(decision_id: UUID, command: HumanCommand) -> CenterDetail:
        return await mutate(decision_id, "REJECT", command)

    @router.post("/{decision_id}/revoke", response_model=CenterDetail)
    async def revoke(decision_id: UUID, command: HumanCommand) -> CenterDetail:
        return await mutate(decision_id, "REVOKE", command)

    @router.post("/{decision_id}/record-execution", response_model=CenterDetail)
    async def execution(decision_id: UUID, command: ManualExecutionCommand) -> CenterDetail:
        return await mutate(decision_id, "RECORD_EXECUTION", command)

    return router
