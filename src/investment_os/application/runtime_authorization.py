"""A scheduled-origin reference is not a grant; the backing authorization must exist."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Annotated, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from investment_os.application.llm_gateway import LLMGatewayFailure, LLMGatewayPort

if TYPE_CHECKING:
    from investment_os.application.analysis_runs import AnalysisQueuedInput


class RuntimeAuthorizationRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    kind: Literal["DAILY_SHADOW"]
    schedule_id: UUID
    revision_id: UUID
    authorization_version: int = Field(strict=True, ge=1)
    authorization_hash: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    intent_id: UUID


class RuntimeEgressBlocked(LLMGatewayFailure):
    """An authoritative check denied a call known not to have entered HTTP."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class AnalysisRuntimeAuthorizationPort(Protocol):
    def prepare_permit(
        self, run_id: UUID, lease: UUID, queued: "AnalysisQueuedInput"
    ) -> AbstractAsyncContextManager[Callable[[], None]]: ...
    def wrap_model(
        self, run_id: UUID, lease: UUID, queued: "AnalysisQueuedInput", delegate: LLMGatewayPort
    ) -> LLMGatewayPort: ...
    def before_model_egress(self) -> None: ...
