"""Tests for bounded, fail-closed single-role Agent execution."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from investment_os.application.agent_registry import AgentRoleRegistry, PromptBundle
from investment_os.application.agent_runtime import (
    AgentRunAttempt,
    AgentRunFailure,
    AgentRunResult,
    AgentRuntime,
)
from investment_os.application.analysis_context import AnalysisEvidence, freeze_analysis_context
from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.llm_gateway import (
    LLMGatewayRequest,
    LLMGatewayResponse,
    SyntheticLLMGateway,
)
from investment_os.domain.agent import AgentRole, AgentTool, OpinionStance
from investment_os.domain.values import UtcTimestamp

NOW = datetime(2026, 9, 19, 0, 0, tzinfo=UTC)
PROMPT_HASH = "a" * 64


def _context() -> tuple[object, object]:
    instrument_id = uuid4()
    evidence = AnalysisEvidence(
        evidence_id=uuid4(),
        content_hash="b" * 64,
        available_at=UtcTimestamp(NOW),
    )
    return (
        freeze_analysis_context(instrument_id, as_of=NOW, evidence=(evidence,)),
        evidence.evidence_id,
    )


def _request(context: object) -> LLMGatewayRequest:
    return LLMGatewayRequest(
        request_id=uuid4(),
        role=AgentRole.MACRO,
        prompt_bundle_hash=PROMPT_HASH,
        input_snapshot_hash=context.input_snapshot_hash,  # type: ignore[union-attr]
        timeout_seconds=30,
        max_output_tokens=300,
    )


def _response(raw_output: str) -> LLMGatewayResponse:
    return LLMGatewayResponse(
        raw_output=raw_output,
        provider="synthetic",
        model_name="fixture-v1",
        latency_ms=1,
        input_tokens=1,
        output_tokens=1,
    )


def _valid_payload(context: object, evidence_id: object) -> str:
    return (
        "{"
        '"schema_version":"1.0",'
        '"agent_role":"MACRO",'
        f'"instrument_id":"{context.instrument_id}",'  # type: ignore[union-attr]
        f'"as_of":"{context.as_of.value.isoformat()}",'  # type: ignore[union-attr]
        '"stance":"POSITIVE",'
        '"confidence":"0.5",'
        '"time_horizon":"DAYS",'
        '"observations":[{'
        '"claim":"Synthetic evidence-backed fact",'
        f'"evidence_ids":["{evidence_id}"],"materiality":"MEDIUM"'
        "}],"
        '"thesis_impacts":[],"assumptions":[],"risks":[],"invalidation_conditions":[],"unknowns":[],"requested_followups":[]'
        "}"
    )


def _runtime(responses: tuple[LLMGatewayResponse, ...]) -> tuple[AgentRuntime, SyntheticLLMGateway]:
    registry = AgentRoleRegistry(
        (
            PromptBundle(
                role=AgentRole.MACRO,
                version="v1",
                content_hash=PROMPT_HASH,
                allowed_tools=(AgentTool.RETRIEVE_EVIDENCE,),
            ),
        )
    )
    gateway = SyntheticLLMGateway(responses)
    return AgentRuntime(registry=registry, gateway=gateway), gateway


async def test_runtime_validates_evidence_backed_output_without_repair() -> None:
    context, evidence_id = _context()
    runtime, gateway = _runtime((_response(_valid_payload(context, evidence_id)),))

    result = await runtime.run(request=_request(context), context=context)

    assert result.opinion.stance is OpinionStance.POSITIVE
    assert result.repair_count == 0
    assert result.failure is None
    assert result.attempts[0].provider == "synthetic"
    assert result.attempts[0].model_name == "fixture-v1"
    assert result.attempts[0].latency_ms == 1
    assert result.raw_output_hashes == (result.attempts[0].raw_output_hash,)
    assert gateway.requests[0].repair_attempt == 0
    assert gateway.requests[0].repair_error_code is None


async def test_runtime_uses_one_sanitized_repair_attempt_for_invalid_json() -> None:
    context, evidence_id = _context()
    runtime, gateway = _runtime(
        (
            _response("not json"),
            _response(_valid_payload(context, evidence_id)),
        )
    )

    result = await runtime.run(request=_request(context), context=context)

    assert result.repair_count == 1
    assert result.failure is None
    assert [request.repair_attempt for request in gateway.requests] == [0, 1]
    assert gateway.requests[1].repair_error_code == "AGENT_OPINION_INVALID"
    assert [attempt.repair_attempt for attempt in result.attempts] == [0, 1]
    assert all("not json" not in attempt.raw_output_hash for attempt in result.attempts)


async def test_runtime_fails_as_insufficient_data_after_two_invalid_repairs() -> None:
    context, _ = _context()
    runtime, gateway = _runtime((_response("bad"), _response("bad"), _response("bad")))

    result = await runtime.run(request=_request(context), context=context)

    assert result.failure is AgentRunFailure.INVALID_OUTPUT
    assert result.repair_count == 2
    assert result.opinion.stance is OpinionStance.INSUFFICIENT_DATA
    assert result.opinion.confidence.value == 0
    assert result.opinion.observations == ()
    assert len(result.raw_output_hashes) == 3
    assert tuple(attempt.raw_output_hash for attempt in result.attempts) == result.raw_output_hashes
    assert len(gateway.requests) == 3


async def test_runtime_rejects_repaired_opinions_that_cite_evidence_outside_the_context() -> None:
    context, _ = _context()
    unavailable_evidence_id = uuid4()
    runtime, _gateway = _runtime(
        (
            _response(_valid_payload(context, unavailable_evidence_id)),
            _response(_valid_payload(context, unavailable_evidence_id)),
            _response(_valid_payload(context, unavailable_evidence_id)),
        )
    )

    result = await runtime.run(request=_request(context), context=context)

    assert result.failure is AgentRunFailure.INVALID_OUTPUT
    assert result.opinion.stance is OpinionStance.INSUFFICIENT_DATA
    assert result.opinion.observations == ()


async def test_runtime_converts_explicit_gateway_failure_to_insufficient_data() -> None:
    context, _ = _context()
    runtime, _gateway = _runtime(())

    result = await runtime.run(request=_request(context), context=context)

    assert result.failure is AgentRunFailure.GATEWAY_FAILURE
    assert result.opinion.stance is OpinionStance.INSUFFICIENT_DATA
    assert result.raw_output_hashes == ()


async def test_runtime_converts_budget_exceeding_gateway_output_to_insufficient_data() -> None:
    context, evidence_id = _context()
    runtime, gateway = _runtime(
        (
            LLMGatewayResponse(
                raw_output=_valid_payload(context, evidence_id),
                provider="synthetic",
                model_name="fixture-v1",
                latency_ms=1,
                input_tokens=1,
                output_tokens=301,
            ),
        )
    )
    request = _request(context)

    result = await runtime.run(request=request, context=context)

    assert result.failure is AgentRunFailure.GATEWAY_FAILURE
    assert result.opinion.stance is OpinionStance.INSUFFICIENT_DATA
    assert gateway.requests == [request]


async def test_runtime_rejects_a_request_with_unregistered_prompt_provenance() -> None:
    context, _ = _context()
    runtime, gateway = _runtime(())
    request = LLMGatewayRequest(
        request_id=uuid4(),
        role=AgentRole.MACRO,
        prompt_bundle_hash="c" * 64,
        input_snapshot_hash=context.input_snapshot_hash,
        timeout_seconds=30,
        max_output_tokens=300,
    )

    with pytest.raises(ApplicationError) as error:
        await runtime.run(request=request, context=context)

    assert error.value.code is ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID
    assert gateway.requests == []


@pytest.mark.parametrize(
    ("provider", "latency_ms", "raw_output_hash"),
    [("", 1, "a" * 64), ("synthetic", -1, "a" * 64), ("synthetic", 1, "A" * 64)],
)
def test_run_attempt_rejects_invalid_sanitized_telemetry(
    provider: str, latency_ms: int, raw_output_hash: str
) -> None:
    with pytest.raises(ApplicationError) as error:
        AgentRunAttempt(
            repair_attempt=0,
            provider=provider,
            model_name="fixture-v1",
            latency_ms=latency_ms,
            input_tokens=1,
            output_tokens=1,
            raw_output_hash=raw_output_hash,
        )

    assert error.value.code is ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID


async def test_run_result_rejects_nonsequential_or_inconsistent_repair_telemetry() -> None:
    context, evidence_id = _context()
    runtime, _gateway = _runtime((_response(_valid_payload(context, evidence_id)),))
    result = await runtime.run(request=_request(context), context=context)

    with pytest.raises(ApplicationError, match="successful"):
        AgentRunResult(
            opinion=result.opinion,
            repair_count=1,
            raw_output_hashes=result.raw_output_hashes,
            attempts=result.attempts,
        )
    with pytest.raises(ApplicationError, match="sequential"):
        AgentRunResult(
            opinion=result.opinion,
            repair_count=0,
            raw_output_hashes=result.raw_output_hashes,
            attempts=(replace(result.attempts[0], repair_attempt=1),),
        )
    with pytest.raises(ApplicationError, match="INSUFFICIENT_DATA"):
        AgentRunResult(
            opinion=result.opinion,
            repair_count=1,
            raw_output_hashes=result.raw_output_hashes,
            attempts=result.attempts,
            failure=AgentRunFailure.GATEWAY_FAILURE,
        )
