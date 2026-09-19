"""Provider-neutral, bounded LLM gateway protocol for synthetic PR-05 execution."""

from collections import deque
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from investment_os.domain.agent import AgentRole
from investment_os.domain.errors import DomainError, DomainErrorCode


def _positive(value: int, field: str) -> int:
    if value <= 0:
        raise DomainError(DomainErrorCode.INVARIANT_VIOLATION, f"{field} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class LLMGatewayRequest:
    request_id: UUID
    role: AgentRole
    prompt_bundle_hash: str
    input_snapshot_hash: str
    timeout_seconds: int
    max_output_tokens: int
    protocol_version: str = "v1"

    def __post_init__(self) -> None:
        _positive(self.timeout_seconds, "timeout_seconds")
        _positive(self.max_output_tokens, "max_output_tokens")
        if (
            self.protocol_version != "v1"
            or not self.prompt_bundle_hash
            or not self.input_snapshot_hash
        ):
            raise DomainError(DomainErrorCode.INVARIANT_VIOLATION, "invalid LLM gateway request")


@dataclass(frozen=True, slots=True)
class LLMGatewayResponse:
    raw_output: str
    provider: str
    model_name: str
    latency_ms: int
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if not self.provider or not self.model_name:
            raise DomainError(DomainErrorCode.INVARIANT_VIOLATION, "gateway provenance is required")
        for value, field in (
            (self.latency_ms, "latency_ms"),
            (self.input_tokens, "input_tokens"),
            (self.output_tokens, "output_tokens"),
        ):
            if value < 0:
                raise DomainError(
                    DomainErrorCode.INVARIANT_VIOLATION, f"{field} must not be negative"
                )


class LLMGatewayPort(Protocol):
    async def complete(self, request: LLMGatewayRequest) -> LLMGatewayResponse: ...


class SyntheticLLMGateway:
    """Test-only gateway: consumes predeclared outputs and never contacts a provider."""

    def __init__(self, responses: tuple[LLMGatewayResponse, ...]) -> None:
        self._responses: deque[LLMGatewayResponse] = deque(responses)
        self.requests: list[LLMGatewayRequest] = []

    async def complete(self, request: LLMGatewayRequest) -> LLMGatewayResponse:
        self.requests.append(request)
        if not self._responses:
            raise RuntimeError("synthetic gateway has no configured response")
        return self._responses.popleft()
