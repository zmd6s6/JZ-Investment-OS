"""Fail-closed orchestration of one bounded, evidence-validated Agent run."""

import json
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256

from investment_os.application.agent_opinion import parse_agent_opinion
from investment_os.application.agent_registry import AgentRoleRegistry
from investment_os.application.analysis_context import AnalysisContext, require_context_evidence
from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.llm_gateway import (
    BoundedLLMGateway,
    LLMGatewayFailure,
    LLMGatewayPort,
    LLMGatewayRequest,
    LLMGatewayResponse,
)
from investment_os.domain.agent import AgentOpinion, OpinionStance
from investment_os.domain.values import Weight


class AgentRunFailure(StrEnum):
    GATEWAY_FAILURE = "GATEWAY_FAILURE"
    INVALID_OUTPUT = "INVALID_OUTPUT"


@dataclass(frozen=True, slots=True)
class AgentRunAttempt:
    """Sanitized provider telemetry for one response; the untrusted response text is omitted."""

    repair_attempt: int
    provider: str
    model_name: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    raw_output_hash: str

    def __post_init__(self) -> None:
        if self.repair_attempt < 0 or self.repair_attempt > 2:
            raise ApplicationError(
                ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID,
                "Agent run telemetry repair attempt must be between zero and two",
            )
        if not self.provider or not self.model_name:
            raise ApplicationError(
                ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID,
                "Agent run telemetry requires provider and model provenance",
            )
        if min(self.latency_ms, self.input_tokens, self.output_tokens) < 0:
            raise ApplicationError(
                ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID,
                "Agent run telemetry values must not be negative",
            )
        if not _is_sha256(self.raw_output_hash):
            raise ApplicationError(
                ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID,
                "Agent run telemetry raw output reference must be a lowercase SHA-256 digest",
            )


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    """Safe outcome with raw-output hashes only; untrusted text never leaves the runner."""

    opinion: AgentOpinion
    repair_count: int
    raw_output_hashes: tuple[str, ...]
    attempts: tuple[AgentRunAttempt, ...]
    failure: AgentRunFailure | None = None

    def __post_init__(self) -> None:
        if self.repair_count < 0 or self.repair_count > 2:
            raise ApplicationError(
                ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID,
                "Agent run repair count must be between zero and two",
            )
        if self.raw_output_hashes != tuple(attempt.raw_output_hash for attempt in self.attempts):
            raise ApplicationError(
                ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID,
                "Agent run telemetry must contain one raw-output hash per response attempt",
            )
        if tuple(attempt.repair_attempt for attempt in self.attempts) != tuple(
            range(len(self.attempts))
        ):
            raise ApplicationError(
                ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID,
                "Agent run telemetry attempts must be sequential and begin at zero",
            )
        if self.failure is None and len(self.attempts) != self.repair_count + 1:
            raise ApplicationError(
                ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID,
                "successful Agent runs must retain every attempt through the successful response",
            )
        if (
            self.failure is AgentRunFailure.GATEWAY_FAILURE
            and len(self.attempts) != self.repair_count
        ):
            raise ApplicationError(
                ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID,
                "gateway failures must retain only the responses received before the failed call",
            )
        if self.failure is AgentRunFailure.INVALID_OUTPUT and (
            self.repair_count != 2 or len(self.attempts) != 3
        ):
            raise ApplicationError(
                ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID,
                "invalid-output failures require the initial attempt and two repairs",
            )


class AgentRuntime:
    """Run a registered role at most once plus two schema-only repair attempts."""

    def __init__(self, *, registry: AgentRoleRegistry, gateway: LLMGatewayPort) -> None:
        self._registry = registry
        self._gateway = BoundedLLMGateway(gateway)

    async def run(self, *, request: LLMGatewayRequest, context: AnalysisContext) -> AgentRunResult:
        bundle = self._registry.require(request.role)
        if request.prompt_bundle_hash != bundle.content_hash:
            raise ApplicationError(
                ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID,
                "LLM gateway request prompt hash does not match the registered role bundle",
            )
        if request.input_snapshot_hash != context.input_snapshot_hash:
            raise ApplicationError(
                ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID,
                "LLM gateway request input hash does not match the frozen AnalysisContext",
            )
        if request.repair_attempt != 0 or request.repair_error_code is not None:
            raise ApplicationError(
                ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID,
                "AgentRuntime accepts only an initial LLM gateway request",
            )

        attempts: list[AgentRunAttempt] = []
        for repair_attempt in range(3):
            attempt_request = replace(
                request,
                repair_attempt=repair_attempt,
                repair_error_code=(
                    None
                    if repair_attempt == 0
                    else ApplicationErrorCode.AGENT_OPINION_INVALID.value
                ),
            )
            try:
                response = await self._gateway.complete(attempt_request)
            except (LLMGatewayFailure, TimeoutError):
                return self._insufficient_data(
                    request=request,
                    context=context,
                    repair_count=repair_attempt,
                    attempts=tuple(attempts),
                    failure=AgentRunFailure.GATEWAY_FAILURE,
                )

            attempts.append(_attempt_telemetry(response=response, repair_attempt=repair_attempt))
            try:
                opinion = _validated_opinion(response=response, request=request, context=context)
            except ApplicationError:
                continue
            return AgentRunResult(
                opinion=opinion,
                repair_count=repair_attempt,
                raw_output_hashes=tuple(attempt.raw_output_hash for attempt in attempts),
                attempts=tuple(attempts),
            )

        return self._insufficient_data(
            request=request,
            context=context,
            repair_count=2,
            attempts=tuple(attempts),
            failure=AgentRunFailure.INVALID_OUTPUT,
        )

    @staticmethod
    def _insufficient_data(
        *,
        request: LLMGatewayRequest,
        context: AnalysisContext,
        repair_count: int,
        attempts: tuple[AgentRunAttempt, ...],
        failure: AgentRunFailure,
    ) -> AgentRunResult:
        return AgentRunResult(
            opinion=AgentOpinion(
                role=request.role,
                instrument_id=context.instrument_id,
                stance=OpinionStance.INSUFFICIENT_DATA,
                confidence=Weight(Decimal("0")),
                time_horizon="runtime failure window",
                observations=(),
                assumptions=(),
                unknowns=(failure.value,),
                risks=(),
            ),
            repair_count=repair_count,
            raw_output_hashes=tuple(attempt.raw_output_hash for attempt in attempts),
            attempts=attempts,
            failure=failure,
        )


def _attempt_telemetry(*, response: LLMGatewayResponse, repair_attempt: int) -> AgentRunAttempt:
    return AgentRunAttempt(
        repair_attempt=repair_attempt,
        provider=response.provider,
        model_name=response.model_name,
        latency_ms=response.latency_ms,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        raw_output_hash=sha256(response.raw_output.encode("utf-8")).hexdigest(),
    )


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _validated_opinion(
    *, response: LLMGatewayResponse, request: LLMGatewayRequest, context: AnalysisContext
) -> AgentOpinion:
    try:
        payload = json.loads(response.raw_output)
    except json.JSONDecodeError as exc:
        raise ApplicationError(
            ApplicationErrorCode.AGENT_OPINION_INVALID,
            "LLM gateway response was not a JSON AgentOpinion payload",
        ) from exc
    opinion = parse_agent_opinion(payload)
    if opinion.role is not request.role or opinion.instrument_id != context.instrument_id:
        raise ApplicationError(
            ApplicationErrorCode.AGENT_OPINION_INVALID,
            "AgentOpinion role or instrument does not match the requested frozen analysis",
        )
    require_context_evidence(opinion, context)
    return opinion
