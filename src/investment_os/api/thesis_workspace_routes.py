"""Local authenticated human Thesis content commands; all research stays explicit."""

from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict

from investment_os.application.thesis_workspace import (
    ThesisCommand,
    ThesisPreview,
    ThesisReceipt,
    ThesisWorkspace,
    ThesisWorkspacePort,
)
from investment_os.domain.errors import DomainError


class ThesisFailureDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str


class ThesisFailureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detail: ThesisFailureDetail


class HumanThesisRoute(APIRoute):
    """Translate only this new workspace's invalid structured inputs."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def validated(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError as error:
                labels = {
                    "instrument_id": "标的编号",
                    "request_id": "请求编号",
                    "expected_version_id": "基线版本编号",
                    "expected_content_hash": "基线内容指纹",
                    "actor_name": "具名研究记录人",
                    "schema_version": "协议版本",
                    "long_term_summary": "长期逻辑摘要",
                    "key": "支柱编号",
                    "description": "事实内容",
                    "evidence_ids": "引用证据",
                    "pillars": "证据支柱",
                    "catalysts": "催化剂",
                    "risks": "风险",
                    "condition": "失效条件",
                    "measurement": "观测指标",
                    "threshold": "失效阈值",
                    "window": "观测窗口",
                    "monitoring_conditions": "监控条件",
                    "state": "逻辑状态",
                    "status": "支柱判断",
                    "change_reason": "修改原因",
                }
                fields = sorted(
                    {
                        labels[part]
                        for item in error.errors()
                        for part in item["loc"]
                        if part in labels
                    }
                )
                field_text = "、".join(fields[:5]) or "结构化逻辑内容"
                raise HTTPException(
                    422,
                    detail={
                        "code": "THESIS_INPUT_INVALID",
                        "message": (
                            f"{field_text}格式不正确或不完整。"
                            "请核对必填文字、唯一支柱与有效证据引用后重新预览。"
                        ),
                    },
                ) from None

        return validated


def thesis_workspace_router(port: ThesisWorkspacePort | None) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/thesis-workspace",
        tags=["thesis-workspace"],
        route_class=HumanThesisRoute,
        responses={status: {"model": ThesisFailureResponse} for status in (409, 422, 503)},
    )

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
            "THESIS_EVIDENCE_MISSING": "引用证据不存在, 请重新选择已入库证据。",
            "THESIS_EVIDENCE_FUTURE": (
                "引用证据的观察、生效、可用或入库时间晚于服务器当前时间, 暂不能保存。"
            ),
            "THESIS_EVIDENCE_EXPIRED": "引用证据已到期, 请选择仍有效的证据后重新预览。",
            "THESIS_EVIDENCE_INVALID": "引用证据质量不足或摄入状态无效, 不能用于此次人工版本。",
            "THESIS_EVIDENCE_WRONG_INSTRUMENT": ("引用证据属于其他标的, 不能保存到当前投资逻辑。"),
            "THESIS_CURRENT_VERSION_MISSING": "已存逻辑版本缺失, 保存禁用。请核对历史数据。",
            "THESIS_VERSION_CORRUPT": "原投资逻辑版本或指纹无法验证, 本次读取和保存已禁用。",
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
