"""Explicit preparation only; no Strategy authorization, approval, or model invocation."""

import re
from uuid import UUID

from fastapi import APIRouter, HTTPException

from investment_os.application.analysis_decision_bridge import (
    AnalysisDecisionBridgePort,
    DecisionBridgeView,
    DecisionQualification,
    DecisionQualificationPort,
    PrepareAnalysisDecision,
)


def analysis_decision_router(
    bridge: AnalysisDecisionBridgePort | None,
    qualifications: DecisionQualificationPort | None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/analysis", tags=["analysis-decision"])

    def available() -> AnalysisDecisionBridgePort:
        if bridge is None:
            raise HTTPException(503, detail={"code": "DECISION_BRIDGE_UNAVAILABLE"})
        return bridge

    @router.get("/decision-qualifications", response_model=tuple[DecisionQualification, ...])
    async def sources(portfolio_id: UUID, instrument_id: UUID) -> tuple[DecisionQualification, ...]:
        if qualifications is None:
            return ()
        try:
            return await qualifications.list(portfolio_id, instrument_id)
        except ValueError:
            raise HTTPException(
                409,
                detail={
                    "code": "DECISION_QUALIFICATION_INVALID",
                    "message": "资格来源校验失败; 不会猜测规则或补齐真实授权。",
                },
            ) from None

    @router.get(
        "/runs/{run_id}/decision-preparations", response_model=tuple[DecisionBridgeView, ...]
    )
    async def history(run_id: UUID) -> tuple[DecisionBridgeView, ...]:
        return await available().history(run_id)

    @router.post("/runs/{run_id}/decision-preparations", response_model=DecisionBridgeView)
    async def prepare(run_id: UUID, command: PrepareAnalysisDecision) -> DecisionBridgeView:
        if run_id != command.run_id:
            raise HTTPException(409, detail={"code": "DECISION_PREPARATION_RUN_CONFLICT"})
        try:
            return await available().prepare(command)
        except LookupError:
            raise HTTPException(404, detail={"code": "ANALYSIS_NOT_FOUND"}) from None
        except ValueError as exc:
            code = str(exc)
            safe = (
                code
                if re.fullmatch(r"(?:DECISION|ANALYSIS)_[A-Z_]+", code)
                else "DECISION_PREPARATION_BLOCKED"
            )
            raise HTTPException(
                409,
                detail={
                    "code": safe,
                    "message": (
                        "未创建待审阅决策: 输入、版本或资格不符。请刷新核对; 不会批准或提交订单。"
                    ),
                },
            ) from None

    return router
