"""Tests for concurrent Round 1 committee execution over one frozen context."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from investment_os.application.agent_registry import AgentRoleRegistry, PromptBundle
from investment_os.application.agent_runtime import AgentRuntime
from investment_os.application.analysis_context import (
    AnalysisContext,
    AnalysisEvidence,
    freeze_analysis_context,
)
from investment_os.application.committee import ROUND_ONE_ROLES
from investment_os.application.committee_runtime import (
    CommitteeRoundResult,
    CommitteeRuntime,
)
from investment_os.application.llm_gateway import (
    LLMGatewayRequest,
    LLMGatewayResponse,
    SyntheticLLMGateway,
)
from investment_os.domain.agent import AgentRole, AgentTool
from investment_os.domain.errors import DomainError
from investment_os.domain.values import UtcTimestamp

NOW = datetime(2026, 9, 19, 0, 0, tzinfo=UTC)
PROMPT_HASH = "a" * 64


def _context() -> tuple[AnalysisContext, object]:
    instrument_id = uuid4()
    evidence = AnalysisEvidence(
        evidence_id=uuid4(),
        content_hash="b" * 64,
        available_at=UtcTimestamp(NOW),
    )
    return freeze_analysis_context(
        instrument_id, as_of=NOW, evidence=(evidence,)
    ), evidence.evidence_id


def _response(
    *, role: AgentRole, stance: str, context: AnalysisContext, evidence_id: object
) -> LLMGatewayResponse:
    return LLMGatewayResponse(
        raw_output=(
            "{"
            '"schema_version":"v1",'
            f'"role":"{role.value}",'
            f'"instrument_id":"{context.instrument_id}",'
            f'"stance":"{stance}",'
            '"confidence":"0.5",'
            '"time_horizon":"synthetic horizon",'
            '"observations":[{'
            '"statement":"Synthetic evidence-backed fact",'
            f'"evidence_ids":["{evidence_id}"]'
            "}],"
            '"assumptions":[],"unknowns":[],"risks":[]'
            "}"
        ),
        provider="synthetic",
        model_name="fixture-v1",
        latency_ms=1,
        input_tokens=1,
        output_tokens=1,
    )


def _runtime(
    context: AnalysisContext, evidence_id: object
) -> tuple[CommitteeRuntime, SyntheticLLMGateway]:
    registry = AgentRoleRegistry(
        tuple(
            PromptBundle(
                role=role,
                version="v1",
                content_hash=PROMPT_HASH,
                allowed_tools=(AgentTool.RETRIEVE_EVIDENCE,),
            )
            for role in ROUND_ONE_ROLES
        )
    )
    gateway = SyntheticLLMGateway(
        tuple(
            _response(role=role, stance="MIXED", context=context, evidence_id=evidence_id)
            for role in ROUND_ONE_ROLES
        )
    )
    return CommitteeRuntime(agent_runtime=AgentRuntime(registry=registry, gateway=gateway)), gateway


def _request_factory(role: AgentRole, context: AnalysisContext) -> LLMGatewayRequest:
    return LLMGatewayRequest(
        request_id=uuid4(),
        role=role,
        prompt_bundle_hash=PROMPT_HASH,
        input_snapshot_hash=context.input_snapshot_hash,
        timeout_seconds=30,
        max_output_tokens=300,
    )


async def test_round_one_runs_every_required_role_against_the_same_frozen_context() -> None:
    context, evidence_id = _context()
    runtime, gateway = _runtime(context, evidence_id)

    result = await runtime.run_round_one(context=context, request_factory=_request_factory)

    assert result.plan.roles == ROUND_ONE_ROLES
    assert tuple(outcome.opinion.role for outcome in result.results) == ROUND_ONE_ROLES
    assert tuple(request.role for request in gateway.requests) == ROUND_ONE_ROLES
    assert {request.input_snapshot_hash for request in gateway.requests} == {
        context.input_snapshot_hash
    }


async def test_round_rejects_a_request_factory_that_impersonates_a_planned_role() -> None:
    context, evidence_id = _context()
    runtime, gateway = _runtime(context, evidence_id)

    def impersonating_factory(
        _role: AgentRole, supplied_context: AnalysisContext
    ) -> LLMGatewayRequest:
        return _request_factory(AgentRole.MACRO, supplied_context)

    with pytest.raises(DomainError, match="preserve planned role identities"):
        await runtime.run_round_one(context=context, request_factory=impersonating_factory)

    assert gateway.requests == []


async def test_round_result_rejects_missing_or_reordered_role_outcomes() -> None:
    context, evidence_id = _context()
    runtime, _gateway = _runtime(context, evidence_id)
    result = await runtime.run_round_one(context=context, request_factory=_request_factory)

    with pytest.raises(DomainError, match="one outcome"):
        CommitteeRoundResult(plan=result.plan, results=result.results[:-1])
    with pytest.raises(DomainError, match="planned role ordering"):
        CommitteeRoundResult(plan=result.plan, results=tuple(reversed(result.results)))


async def test_session_executes_exactly_two_rounds_with_targeted_rebuttal_and_devils_advocate() -> (
    None
):
    context, evidence_id = _context()
    round_one_stances = {
        AgentRole.MACRO: "POSITIVE",
        AgentRole.INDUSTRY: "MIXED",
        AgentRole.FUNDAMENTAL: "NEGATIVE",
        AgentRole.MARKET_QUANT: "MIXED",
        AgentRole.EVENT: "MIXED",
    }
    registry = AgentRoleRegistry(
        tuple(
            PromptBundle(
                role=role,
                version="v1",
                content_hash=PROMPT_HASH,
                allowed_tools=(AgentTool.RETRIEVE_EVIDENCE,),
            )
            for role in (*ROUND_ONE_ROLES, AgentRole.DEVILS_ADVOCATE)
        )
    )
    second_round_roles = (AgentRole.DEVILS_ADVOCATE, AgentRole.FUNDAMENTAL, AgentRole.MACRO)
    gateway = SyntheticLLMGateway(
        tuple(
            _response(
                role=role,
                stance=round_one_stances[role],
                context=context,
                evidence_id=evidence_id,
            )
            for role in ROUND_ONE_ROLES
        )
        + tuple(
            _response(role=role, stance="MIXED", context=context, evidence_id=evidence_id)
            for role in second_round_roles
        )
    )
    runtime = CommitteeRuntime(agent_runtime=AgentRuntime(registry=registry, gateway=gateway))

    result = await runtime.run_session(context=context, request_factory=_request_factory)

    assert len(result.rounds) == 2
    assert result.rounds[1].plan.roles == second_round_roles
    assert result.rounds[1].plan.conflicts
    assert tuple(request.role for request in gateway.requests) == (
        *ROUND_ONE_ROLES,
        *second_round_roles,
    )
