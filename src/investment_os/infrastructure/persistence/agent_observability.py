"""Safe translation of completed Agent runs into append-only persistence records."""

import json
from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256
from uuid import UUID, uuid4

from investment_os.application.agent_registry import PromptBundle
from investment_os.application.agent_runtime import AgentRunResult
from investment_os.application.analysis_context import AnalysisContext
from investment_os.application.committee_runtime import CommitteeSessionResult
from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.llm_gateway import LLMGatewayRequest
from investment_os.infrastructure.persistence.models import (
    AgentOpinionRecord,
    AgentRunRecord,
    CommitteeMessageRecord,
    CommitteeSessionRecord,
    ConflictRecord,
)


def agent_run_record_from_result(
    *,
    run_id: UUID | None = None,
    request: LLMGatewayRequest,
    prompt_bundle: PromptBundle,
    result: AgentRunResult,
    started_at: datetime,
    ended_at: datetime,
    created_by: str,
    correlation_id: UUID,
) -> AgentRunRecord:
    """Build a complete audit row without retaining untrusted raw provider output."""

    _validate_provenance(request=request, prompt_bundle=prompt_bundle, result=result)
    latest = result.attempts[-1] if result.attempts else None
    return AgentRunRecord(
        id=run_id or uuid4(),
        agent_role=request.role.value,
        model_provider=latest.provider if latest is not None else "unavailable",
        model_name=latest.model_name if latest is not None else "unavailable",
        prompt_version=prompt_bundle.version,
        input_snapshot_hash=request.input_snapshot_hash,
        started_at=started_at,
        ended_at=ended_at,
        status="SUCCEEDED" if result.failure is None else "INSUFFICIENT_DATA",
        token_usage_json={
            "input": sum(attempt.input_tokens for attempt in result.attempts),
            "output": sum(attempt.output_tokens for attempt in result.attempts),
            "cost": str(sum((attempt.total_cost or 0) for attempt in result.attempts)),
        },
        error_code=result.failure.value if result.failure is not None else None,
        created_by=created_by,
        correlation_id=correlation_id,
        metadata_json={
            "prompt_bundle_hash": prompt_bundle.content_hash,
            "committee_context_hash": request.committee_context_hash,
            "allowed_tools": [tool.value for tool in prompt_bundle.allowed_tools],
            "repair_count": result.repair_count,
            "latency_ms": sum(attempt.latency_ms for attempt in result.attempts),
            "attempts": [
                {
                    "repair_attempt": attempt.repair_attempt,
                    "provider": attempt.provider,
                    "model_name": attempt.model_name,
                    "latency_ms": attempt.latency_ms,
                    "input_tokens": attempt.input_tokens,
                    "output_tokens": attempt.output_tokens,
                    "raw_output_hash": attempt.raw_output_hash,
                    "total_cost": str(attempt.total_cost)
                    if attempt.total_cost is not None
                    else None,
                    "pricing_version": attempt.pricing_version,
                    "budget_window_date": attempt.budget_window_date,
                }
                for attempt in result.attempts
            ],
        },
    )


def agent_opinion_record_from_result(
    *,
    opinion_id: UUID | None = None,
    agent_run_id: UUID,
    result: AgentRunResult,
    created_by: str,
    correlation_id: UUID,
) -> AgentOpinionRecord:
    """Persist only the validated structured opinion and evidence identifiers."""

    opinion = result.opinion
    payload = {
        "schema_version": opinion.schema_version,
        "agent_role": opinion.role.value,
        "instrument_id": str(opinion.instrument_id),
        "as_of": opinion.as_of.value.isoformat() if opinion.as_of is not None else None,
        "stance": opinion.stance.value,
        "confidence": str(opinion.confidence.value),
        "time_horizon": opinion.time_horizon,
        "observations": [
            {
                "claim": observation.claim,
                "evidence_ids": [str(evidence_id) for evidence_id in observation.evidence_ids],
                "materiality": observation.materiality.value,
            }
            for observation in opinion.observations
        ],
        "thesis_impacts": [
            {
                "pillar_key": item.pillar_key,
                "impact": item.impact.value,
                "reason": item.reason,
                "evidence_ids": [str(evidence_id) for evidence_id in item.evidence_ids],
            }
            for item in opinion.thesis_impacts
        ],
        "assumptions": list(opinion.assumptions),
        "unknowns": list(opinion.unknowns),
        "risks": [
            {
                "code": item.code,
                "severity": item.severity.value,
                "evidence_ids": [str(evidence_id) for evidence_id in item.evidence_ids],
            }
            for item in opinion.risks
        ],
        "invalidation_conditions": [
            {"condition": item.condition, "observable": item.observable}
            for item in opinion.invalidation_conditions
        ],
        "requested_followups": list(opinion.requested_followups),
    }
    content_hash = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )
    ).hexdigest()
    return AgentOpinionRecord(
        id=opinion_id or uuid4(),
        agent_run_id=agent_run_id,
        instrument_id=opinion.instrument_id,
        stance=opinion.stance.value,
        confidence=opinion.confidence.value,
        time_horizon=opinion.time_horizon,
        observations_json=payload["observations"],
        thesis_impacts_json=payload["thesis_impacts"],
        assumptions_json=payload["assumptions"],
        risks_json=payload["risks"],
        invalidation_conditions_json=payload["invalidation_conditions"],
        unknowns_json=payload["unknowns"],
        content_hash=content_hash,
        created_by=created_by,
        correlation_id=correlation_id,
        metadata_json={"agent_opinion_schema_version": opinion.schema_version},
    )


def committee_session_record_from_result(
    *,
    session_id: UUID | None = None,
    result: CommitteeSessionResult,
    context: AnalysisContext,
    started_at: datetime,
    completed_at: datetime,
    created_by: str,
    correlation_id: UUID,
) -> CommitteeSessionRecord:
    """Map a finite committee result to one auditable, non-decision session row."""

    round_two = result.rounds[1]
    return CommitteeSessionRecord(
        id=session_id or uuid4(),
        instrument_id=context.instrument_id,
        session_type="TWO_ROUND_RESEARCH",
        round_count=len(result.rounds),
        status="COMPLETED",
        input_snapshot_hash=_session_input_hash(result=result, context=context),
        started_at=started_at,
        completed_at=completed_at,
        created_by=created_by,
        correlation_id=correlation_id,
        metadata_json={
            "committee_protocol_version": "v1",
            "unresolved_conflict_count": len(round_two.plan.conflicts),
        },
    )


def committee_message_records_from_result(
    *,
    session_id: UUID,
    result: CommitteeSessionResult,
    opinion_ids: Mapping[tuple[int, str], UUID],
    created_by: str,
    correlation_id: UUID,
) -> tuple[CommitteeMessageRecord, ...]:
    """Persist only validated structured outcomes, referenced by their opinion IDs."""

    expected_keys = {
        (round_result.plan.number, run_result.opinion.role.value)
        for round_result in result.rounds
        for run_result in round_result.results
    }
    if set(opinion_ids) != expected_keys:
        raise ApplicationError(
            ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID,
            "committee message mapping requires exactly one opinion ID per round and role",
        )

    return tuple(
        CommitteeMessageRecord(
            session_id=session_id,
            round_number=round_result.plan.number,
            agent_role=run_result.opinion.role.value,
            message_type=(
                "INDEPENDENT_OPINION" if round_result.plan.number == 1 else "TARGETED_REBUTTAL"
            ),
            opinion_id=opinion_ids[(round_result.plan.number, run_result.opinion.role.value)],
            targets_opinion_id=None,
            payload_json={
                "agent_opinion_schema_version": run_result.opinion.schema_version,
                "stance": run_result.opinion.stance.value,
                "confidence": str(run_result.opinion.confidence.value),
                "failure": run_result.failure.value if run_result.failure is not None else None,
            },
            created_by=created_by,
            correlation_id=correlation_id,
        )
        for round_result in result.rounds
        for run_result in round_result.results
    )


def conflict_records_from_result(
    *,
    session_id: UUID,
    result: CommitteeSessionResult,
    opinion_ids: Mapping[tuple[int, str], UUID],
    created_by: str,
    correlation_id: UUID,
) -> tuple[ConflictRecord, ...]:
    """Keep every unresolved deterministic conflict explicit after the final allowed round."""

    round_two = result.rounds[1]
    required_keys = {
        (1, role.value) for conflict in round_two.plan.conflicts for role in conflict.roles
    }
    if not required_keys.issubset(opinion_ids):
        raise ApplicationError(
            ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID,
            "conflict mapping requires the conflicting round-one opinion IDs",
        )
    return tuple(
        ConflictRecord(
            session_id=session_id,
            conflict_type=conflict.kind.value,
            severity="MATERIAL",
            opinion_ids=[str(opinion_ids[(1, role.value)]) for role in conflict.roles],
            question="Resolve the deterministic stance disagreement through bounded review.",
            resolution=None,
            created_by=created_by,
            correlation_id=correlation_id,
            metadata_json={
                "committee_protocol_version": "v1",
                "stances": [
                    {"role": role.value, "stance": stance.value}
                    for role, stance in conflict.stances
                ],
            },
        )
        for conflict in round_two.plan.conflicts
    )


def _session_input_hash(*, result: CommitteeSessionResult, context: AnalysisContext) -> str:
    """Return the original immutable AnalysisContext hash shared by every committee role."""

    instrument_ids = {
        run_result.opinion.instrument_id
        for round_result in result.rounds
        for run_result in round_result.results
    }
    if instrument_ids != {context.instrument_id}:
        raise ApplicationError(
            ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID,
            "committee session mapping requires one instrument across all results",
        )
    return context.input_snapshot_hash


def _validate_provenance(
    *, request: LLMGatewayRequest, prompt_bundle: PromptBundle, result: AgentRunResult
) -> None:
    if (
        request.role is not prompt_bundle.role
        or request.role is not result.opinion.role
        or request.prompt_bundle_hash != prompt_bundle.content_hash
    ):
        raise ApplicationError(
            ApplicationErrorCode.AGENT_RUNTIME_REQUEST_INVALID,
            "Agent observability record provenance does not match the completed runtime result",
        )
