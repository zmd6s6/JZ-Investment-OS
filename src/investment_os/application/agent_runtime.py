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
class AgentRunResult:
    """Safe outcome with raw-output hashes only; untrusted text never leaves the runner."""

    opinion: AgentOpinion
    repair_count: int
    raw_output_hashes: tuple[str, ...]
    failure: AgentRunFailure | None = None


class AgentRuntime:
    """Run a registered role at most once plus two schema-only repair attempts."""

    def __init__(self, *, registry: AgentRoleRegistry, gateway: LLMGatewayPort) -> None:
        self._registry = registry
        self._gateway = gateway

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

        raw_output_hashes: list[str] = []
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
                    raw_output_hashes=tuple(raw_output_hashes),
                    failure=AgentRunFailure.GATEWAY_FAILURE,
                )

            raw_output_hashes.append(_raw_output_hash(response))
            try:
                opinion = _validated_opinion(response=response, request=request, context=context)
            except ApplicationError:
                continue
            return AgentRunResult(
                opinion=opinion,
                repair_count=repair_attempt,
                raw_output_hashes=tuple(raw_output_hashes),
            )

        return self._insufficient_data(
            request=request,
            context=context,
            repair_count=2,
            raw_output_hashes=tuple(raw_output_hashes),
            failure=AgentRunFailure.INVALID_OUTPUT,
        )

    @staticmethod
    def _insufficient_data(
        *,
        request: LLMGatewayRequest,
        context: AnalysisContext,
        repair_count: int,
        raw_output_hashes: tuple[str, ...],
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
            raw_output_hashes=raw_output_hashes,
            failure=failure,
        )


def _raw_output_hash(response: LLMGatewayResponse) -> str:
    return sha256(response.raw_output.encode("utf-8")).hexdigest()


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
