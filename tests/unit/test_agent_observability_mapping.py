"""Tests for sanitizing completed Agent runtime results before persistence."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from investment_os.application.agent_registry import PromptBundle
from investment_os.application.agent_runtime import AgentRunAttempt, AgentRunFailure, AgentRunResult
from investment_os.application.analysis_context import (
    AnalysisContext,
    AnalysisEvidence,
    freeze_analysis_context,
)
from investment_os.application.committee import (
    ROUND_ONE_ROLES,
    detect_stance_conflicts,
    plan_round_one,
    plan_round_two,
)
from investment_os.application.committee_runtime import (
    CommitteeRoundResult,
    CommitteeSessionResult,
)
from investment_os.application.errors import ApplicationError
from investment_os.application.llm_gateway import LLMGatewayRequest
from investment_os.domain.agent import (
    AgentOpinion,
    AgentRole,
    AgentTool,
    EvidenceBackedObservation,
    OpinionStance,
)
from investment_os.domain.values import UtcTimestamp, Weight
from investment_os.infrastructure.persistence.agent_observability import (
    agent_opinion_record_from_result,
    agent_run_record_from_result,
    committee_message_records_from_result,
    committee_session_record_from_result,
    conflict_records_from_result,
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


def _committee_context() -> tuple[AnalysisContext, UUID]:
    evidence = AnalysisEvidence(
        evidence_id=uuid4(),
        content_hash="e" * 64,
        available_at=UtcTimestamp(NOW),
    )
    context = freeze_analysis_context(uuid4(), as_of=NOW, evidence=(evidence,))
    return context, evidence.evidence_id


def _committee_run(
    *, context: AnalysisContext, evidence_id: UUID, role: AgentRole, stance: OpinionStance
) -> AgentRunResult:
    return AgentRunResult(
        opinion=AgentOpinion(
            role=role,
            instrument_id=context.instrument_id,
            stance=stance,
            confidence=Weight(Decimal("0.5")),
            time_horizon="synthetic horizon",
            observations=(EvidenceBackedObservation("Synthetic fact", (evidence_id,)),),
            assumptions=(),
            unknowns=(),
            risks=(),
        ),
        repair_count=0,
        raw_output_hashes=(),
        attempts=(),
    )


def _committee_result(context: AnalysisContext, evidence_id: UUID) -> CommitteeSessionResult:
    round_one_stances = {
        AgentRole.MACRO: OpinionStance.POSITIVE,
        AgentRole.INDUSTRY: OpinionStance.MIXED,
        AgentRole.FUNDAMENTAL: OpinionStance.NEGATIVE,
        AgentRole.MARKET_QUANT: OpinionStance.MIXED,
        AgentRole.EVENT: OpinionStance.MIXED,
    }
    round_one_results = tuple(
        _committee_run(
            context=context,
            evidence_id=evidence_id,
            role=role,
            stance=round_one_stances[role],
        )
        for role in ROUND_ONE_ROLES
    )
    conflicts = detect_stance_conflicts(tuple(run.opinion for run in round_one_results))
    round_two_plan = plan_round_two(conflicts)
    round_two_results = tuple(
        _committee_run(
            context=context,
            evidence_id=evidence_id,
            role=role,
            stance=OpinionStance.MIXED,
        )
        for role in round_two_plan.roles
    )
    return CommitteeSessionResult(
        rounds=(
            CommitteeRoundResult(plan=plan_round_one(), results=round_one_results),
            CommitteeRoundResult(plan=round_two_plan, results=round_two_results),
        )
    )


def _opinion_ids(result: CommitteeSessionResult) -> dict[tuple[int, str], UUID]:
    return {
        (round_result.plan.number, run_result.opinion.role.value): uuid4()
        for round_result in result.rounds
        for run_result in round_result.results
    }


def test_committee_mappings_keep_finite_session_and_unresolved_conflict_auditable() -> None:
    context, evidence_id = _committee_context()
    result = _committee_result(context, evidence_id)
    correlation_id = uuid4()
    opinion_ids = _opinion_ids(result)

    session_record = committee_session_record_from_result(
        result=result,
        context=context,
        started_at=NOW,
        completed_at=NOW,
        created_by="pytest",
        correlation_id=correlation_id,
    )
    messages = committee_message_records_from_result(
        session_id=session_record.id,
        result=result,
        opinion_ids=opinion_ids,
        created_by="pytest",
        correlation_id=correlation_id,
    )
    conflicts = conflict_records_from_result(
        session_id=session_record.id,
        result=result,
        opinion_ids=opinion_ids,
        created_by="pytest",
        correlation_id=correlation_id,
    )

    assert session_record.round_count == 2
    assert session_record.input_snapshot_hash == context.input_snapshot_hash
    assert session_record.metadata_json["unresolved_conflict_count"] == 1
    assert len(messages) == sum(len(round_result.results) for round_result in result.rounds)
    assert {message.message_type for message in messages} == {
        "INDEPENDENT_OPINION",
        "TARGETED_REBUTTAL",
    }
    assert len(conflicts) == 1
    assert conflicts[0].resolution is None
    assert conflicts[0].opinion_ids == [
        str(opinion_ids[(1, role.value)]) for role in result.rounds[1].plan.conflicts[0].roles
    ]


def test_committee_message_mapping_rejects_missing_opinion_provenance() -> None:
    context, evidence_id = _committee_context()
    result = _committee_result(context, evidence_id)
    opinion_ids = _opinion_ids(result)
    opinion_ids.pop(next(iter(opinion_ids)))

    with pytest.raises(ApplicationError, match="exactly one opinion ID"):
        committee_message_records_from_result(
            session_id=uuid4(),
            result=result,
            opinion_ids=opinion_ids,
            created_by="pytest",
            correlation_id=uuid4(),
        )
