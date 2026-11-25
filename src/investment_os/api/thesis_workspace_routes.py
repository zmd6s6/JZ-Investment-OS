"""Local authenticated human Thesis content commands; all research stays explicit."""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from investment_os.application.thesis_workspace import (
    ThesisCommand,
    ThesisPreview,
    ThesisReceipt,
    ThesisWorkspace,
    ThesisWorkspacePort,
)
from investment_os.domain.errors import DomainError


def thesis_workspace_router(port: ThesisWorkspacePort | None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/thesis-workspace", tags=["thesis-workspace"])

    def available() -> ThesisWorkspacePort:
        if port is None:
            raise HTTPException(
                503,
                detail={
                    "code": "THESIS_WORKSPACE_UNAVAILABLE",
                    "message": "投资逻辑服务未装配, 不能读取或保存。",
                },
            )
        return port

    def failure(error: ValueError | DomainError) -> HTTPException:
        code = str(error)
        if not code.startswith("THESIS_"):
            code = "THESIS_INPUT_INVALID"
        messages = {
            "THESIS_BASELINE_CONFLICT": (
                "已保存版本发生变化。草稿保留, 请明确重新读取基线后核对, 不会覆盖他人修订。"
            ),
            "THESIS_REQUEST_CONFLICT": "该请求编号已用于其他内容或标的, 请核对原请求结果。",
            "THESIS_STATE_CHANGE_FORBIDDEN": (
                "只能初建 UNKNOWN 或修订原状态内容; 此入口不能提升状态或恢复失效逻辑。"
            ),
            "THESIS_INSTRUMENT_NOT_FOUND": "标的不存在, 请从已有目录重新选择。",
        }
        message = messages.get(
            code, "逻辑内容或证据无效、已过期、尚未可用或归属不符。请核对当前来源后重新预览。"
        )
        return HTTPException(
            409 if "CONFLICT" in code else 422, detail={"code": code, "message": message}
        )

    @router.get("/{instrument_id}", response_model=ThesisWorkspace)
    async def read(instrument_id: UUID) -> ThesisWorkspace:
        try:
            return await available().read(instrument_id)
        except (ValueError, DomainError) as error:
            raise failure(error) from None

    @router.post("/preview", response_model=ThesisPreview)
    async def preview(command: ThesisCommand) -> ThesisPreview:
        try:
            return await available().preview(command)
        except (ValueError, DomainError) as error:
            raise failure(error) from None

    @router.post("/save", response_model=ThesisReceipt)
    async def save(command: ThesisCommand) -> ThesisReceipt:
        try:
            return await available().save(command)
        except (ValueError, DomainError) as error:
            raise failure(error) from None

    return router
