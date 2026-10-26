"""模型前确定性组合上下文及只追加记录端口。"""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Final, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from investment_os.application.analysis_models import digest
from investment_os.application.analysis_valuation import AnalysisValuation

FEATURE_SET: Final = "analysis-portfolio-context-v1"


def execution_input_hash(request_hash: str, valuation: AnalysisValuation) -> str:
    return digest(
        {
            "schema_version": "1.0",
            "feature_set_version": FEATURE_SET,
            "request_input_hash": request_hash,
            "valuation": valuation.model_dump(mode="json"),
        }
    )


class ExecutionContextReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID
    feature_snapshot_id: UUID
    feature_set_version: Literal["analysis-portfolio-context-v1"] = FEATURE_SET
    request_input_hash: str
    runtime_input_hash: str
    content_hash: str
    recorded_at: datetime


class ExecutionContextView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID
    status: Literal["RECORDED", "NOT_RECORDED"]
    receipt: ExecutionContextReceipt | None = None
    valuation: AnalysisValuation | None = None


class ExecutionContextFailure(RuntimeError):
    """准备输入未能可靠提交, 不得继续调用模型。"""


ContextRecorder = Callable[[AnalysisValuation], Awaitable[ExecutionContextReceipt]]


class AnalysisExecutionContextStore(Protocol):
    async def save(
        self, run_id: UUID, valuation: AnalysisValuation, *, worker_token: UUID | None = None
    ) -> ExecutionContextReceipt: ...
    async def read(self, run_id: UUID) -> ExecutionContextView: ...
