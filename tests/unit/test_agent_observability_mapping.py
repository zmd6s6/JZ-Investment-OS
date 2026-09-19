"""Tests for sanitizing completed Agent runtime results before persistence."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from investment_os.application.agent_registry import PromptBundle
from investment_os.application.agent_runtime import AgentRunAttempt, AgentRunFailure, AgentRunResult
from investment_os.application.errors import ApplicationError
from investment_os.application.llm_gateway import LLMGatewayRequest
from investment_os.domain.agent import (
    AgentOpinion,
    AgentRole,
    AgentTool,
    EvidenceBackedObservation,
    OpinionStance,
)
from investment_os.domain.values import Weight
from investment_os.infrastructure.persistence.agent_observability import (
    agent_opinion_record_from_result,
    agent_run_record_from_result,
)

NOW = datetime(2026, 9, 19, 0, 0, tzinfo=UTC)
PROMPT_HASH = "a" * 64


def _request() -> LLMGatewayRequest:
    return LLMGatewayRequest(
        request_id=uuid4(),
        role=AgentRole.MACRO,
        prompt_bundle_hash=PROMPT_HASH,
        input_snapshot_hash="b" * 64,
        timeout_seconds=30,
        max_output_tokens=300,
    )


def _bundle() -> PromptBundle:
    return PromptBundle(
        role=AgentRole.MACRO,
        version="v1",
        content_hash=PROMPT_HASH,
        allowed_tools=(AgentTool.RETRIEVE_EVIDENCE,),
    )


def _result(*, failure: AgentRunFailure | None = None) -> AgentRunResult:
    opinion = AgentOpinion(
        role=AgentRole.MACRO,
        instrument_id=uuid4(),
        stance=OpinionStance.INSUFFICIENT_DATA if failure else OpinionStance.POSITIVE,
        confidence=Weight(Decimal("0") if failure else Decimal("0.5")),
        time_horizon="synthetic horizon",
        observations=(
            () if failure else (EvidenceBackedObservation("Synthetic fact", (uuid4(),)),)
        ),
        assumptions=(),
        unknowns=(failure.value,) if failure else (),
        risks=(),
    )
    attempts = (
        AgentRunAttempt(
            repair_attempt=0,
            provider="synthetic",
            model_name="fixture-v1",
            latency_ms=7,
            input_tokens=11,
            output_tokens=13,
            raw_output_hash="c" * 64,
        ),
    )
    return AgentRunResult(
        opinion=opinion,
        repair_count=0,
        raw_output_hashes=("c" * 64,),
        attempts=attempts,
        failure=failure,
    )


def test_mapping_preserves_required_provenance_without_raw_model_output() -> None:
    request = _request()
    result = _result()
    run_record = agent_run_record_from_result(
        request=request,
        prompt_bundle=_bundle(),
        result=result,
        started_at=NOW,
        ended_at=NOW,
        created_by="pytest",
        correlation_id=uuid4(),
    )
    opinion_record = agent_opinion_record_from_result(
        agent_run_id=run_record.id,
        result=result,
        created_by="pytest",
        correlation_id=run_record.correlation_id,
    )

    assert run_record.status == "SUCCEEDED"
    assert run_record.token_usage_json == {"input": 11, "output": 13}
    assert run_record.metadata_json["attempts"][0]["raw_output_hash"] == "c" * 64
    assert "raw_output" not in run_record.metadata_json
    assert "raw_output" not in run_record.metadata_json["attempts"][0]
    assert opinion_record.observations_json[0]["evidence_ids"]
    assert opinion_record.content_hash


def test_mapping_keeps_explicit_insufficient_data_failure() -> None:
    result = _result(failure=AgentRunFailure.GATEWAY_FAILURE)

    record = agent_run_record_from_result(
        request=_request(),
        prompt_bundle=_bundle(),
        result=result,
        started_at=NOW,
        ended_at=NOW,
        created_by="pytest",
        correlation_id=uuid4(),
    )

    assert record.status == "INSUFFICIENT_DATA"
    assert record.error_code == "GATEWAY_FAILURE"


def test_mapping_rejects_mismatched_prompt_provenance() -> None:
    request = _request()
    bundle = PromptBundle(
        role=AgentRole.MACRO,
        version="v1",
        content_hash="d" * 64,
        allowed_tools=(AgentTool.RETRIEVE_EVIDENCE,),
    )

    with pytest.raises(ApplicationError, match="provenance"):
        agent_run_record_from_result(
            request=request,
            prompt_bundle=bundle,
            result=_result(),
            started_at=NOW,
            ended_at=NOW,
            created_by="pytest",
            correlation_id=uuid4(),
        )
