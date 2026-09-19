from uuid import uuid4

import pytest

from investment_os.application.llm_gateway import (
    BoundedLLMGateway,
    LLMGatewayFailure,
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


def test_gateway_request_rejects_non_sha256_committee_context_reference() -> None:
    with pytest.raises(DomainError, match="committee_context_hash"):
        LLMGatewayRequest(
            request_id=uuid4(),
            role=AgentRole.EVENT,
            prompt_bundle_hash="a" * 64,
            input_snapshot_hash="b" * 64,
            timeout_seconds=1,
            max_output_tokens=1,
            committee_context_hash="not-a-hash",
        )


async def test_synthetic_gateway_fails_explicitly_when_no_response_is_configured() -> None:
    with pytest.raises(RuntimeError, match="no configured response"):
        await SyntheticLLMGateway(()).complete(_request())


@pytest.mark.parametrize(
    ("output_tokens", "latency_ms", "error"),
    [
        (500, 30_000, None),
        (501, 30_000, "output-token"),
        (500, 30_001, "timeout"),
    ],
)
async def test_bounded_gateway_enforces_the_request_token_and_timeout_limits(
    output_tokens: int, latency_ms: int, error: str | None
) -> None:
    request = _request()
    gateway = BoundedLLMGateway(
        SyntheticLLMGateway(
            (
                LLMGatewayResponse(
                    raw_output='{"schema_version":"v1"}',
                    provider="synthetic",
                    model_name="fixture-v1",
                    latency_ms=latency_ms,
                    input_tokens=10,
                    output_tokens=output_tokens,
                ),
            )
        )
    )

    if error is None:
        assert (await gateway.complete(request)).output_tokens == output_tokens
    else:
        with pytest.raises(LLMGatewayFailure, match=error):
            await gateway.complete(request)
