from uuid import uuid4

import pytest

from investment_os.application.llm_gateway import (
    LLMGatewayRequest,
    LLMGatewayResponse,
    SyntheticLLMGateway,
)
from investment_os.domain.agent import AgentRole
from investment_os.domain.errors import DomainError


def _request() -> LLMGatewayRequest:
    return LLMGatewayRequest(
        request_id=uuid4(),
        role=AgentRole.MACRO,
        prompt_bundle_hash="a" * 64,
        input_snapshot_hash="b" * 64,
        timeout_seconds=30,
        max_output_tokens=500,
    )


def _response() -> LLMGatewayResponse:
    return LLMGatewayResponse(
        raw_output='{"schema_version":"v1"}',
        provider="synthetic",
        model_name="fixture-v1",
        latency_ms=1,
        input_tokens=10,
        output_tokens=5,
    )


async def test_synthetic_gateway_records_bounded_request_and_returns_configured_output() -> None:
    gateway = SyntheticLLMGateway((_response(),))
    request = _request()

    response = await gateway.complete(request)

    assert response.provider == "synthetic"
    assert gateway.requests == [request]


@pytest.mark.parametrize("timeout_seconds,max_output_tokens", [(0, 1), (1, 0), (-1, 1)])
def test_gateway_request_rejects_unbounded_or_invalid_budgets(
    timeout_seconds: int, max_output_tokens: int
) -> None:
    with pytest.raises(DomainError):
        LLMGatewayRequest(
            request_id=uuid4(),
            role=AgentRole.EVENT,
            prompt_bundle_hash="a",
            input_snapshot_hash="b",
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens,
        )


@pytest.mark.parametrize(
    ("repair_attempt", "repair_error_code"),
    [(3, "AGENT_OPINION_INVALID"), (1, None), (0, "AGENT_OPINION_INVALID")],
)
def test_gateway_request_rejects_unbounded_or_ambiguous_repair_metadata(
    repair_attempt: int, repair_error_code: str | None
) -> None:
    with pytest.raises(DomainError):
        LLMGatewayRequest(
            request_id=uuid4(),
            role=AgentRole.EVENT,
            prompt_bundle_hash="a" * 64,
            input_snapshot_hash="b" * 64,
            timeout_seconds=1,
            max_output_tokens=1,
            repair_attempt=repair_attempt,
            repair_error_code=repair_error_code,
        )


async def test_synthetic_gateway_fails_explicitly_when_no_response_is_configured() -> None:
    with pytest.raises(RuntimeError, match="no configured response"):
        await SyntheticLLMGateway(()).complete(_request())
