"""Concurrent, bounded execution of a committee round against one frozen context."""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256

from investment_os.application.agent_runtime import AgentRunResult, AgentRuntime
from investment_os.application.analysis_context import AnalysisContext
from investment_os.application.committee import (
    CommitteeConflict,
    CommitteeRound,
    detect_stance_conflicts,
    plan_round_one,
    plan_round_two,
)
from investment_os.application.llm_gateway import LLMGatewayRequest
from investment_os.domain.agent import AgentRole
from investment_os.domain.errors import DomainError, DomainErrorCode


@dataclass(frozen=True, slots=True)
class CommitteeRoleInput:
    """Structured, untrusted-data-only input supplied to a role-specific prompt builder."""

    context: AnalysisContext
    visible_opinions: tuple[AgentRunResult, ...] = ()
    conflicts: tuple[CommitteeConflict, ...] = ()

    @property
    def content_hash(self) -> str | None:
        if not self.visible_opinions and not self.conflicts:
            return None
        payload = {
            "analysis_context_hash": self.context.input_snapshot_hash,
            "opinions": [
                {
                    "role": result.opinion.role.value,
                    "stance": result.opinion.stance.value,
                    "confidence": str(result.opinion.confidence.value),
                    "observations": [
                        {
                            "statement": observation.statement,
                            "evidence_ids": [
                                str(evidence_id) for evidence_id in observation.evidence_ids
                            ],
                        }
                        for observation in result.opinion.observations
                    ],
                    "assumptions": list(result.opinion.assumptions),
                    "unknowns": list(result.opinion.unknowns),
                    "risks": list(result.opinion.risks),
                }
                for result in self.visible_opinions
            ],
            "conflicts": [
                {
                    "kind": conflict.kind.value,
                    "roles": [role.value for role in conflict.roles],
                    "stances": [(role.value, stance.value) for role, stance in conflict.stances],
                }
                for conflict in self.conflicts
            ],
        }
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
                "utf-8"
            )
        ).hexdigest()


RequestFactory = Callable[[AgentRole, CommitteeRoleInput], LLMGatewayRequest]


@dataclass(frozen=True, slots=True)
class CommitteeRoundResult:
    """Ordered, explicit role outcomes from exactly one legal committee round."""

    plan: CommitteeRound
    results: tuple[AgentRunResult, ...]
    requests: tuple[LLMGatewayRequest, ...] = ()

    def __post_init__(self) -> None:
        if len(self.results) != len(self.plan.roles):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "committee round result must have one outcome for every planned role",
            )
        if tuple(result.opinion.role for result in self.results) != self.plan.roles:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "committee round outcomes must retain planned role ordering",
            )
        if self.requests and (
            len(self.requests) != len(self.plan.roles)
            or tuple(request.role for request in self.requests) != self.plan.roles
        ):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "committee round requests must retain planned role ordering",
            )
        if (
            self.requests
            and self.plan.number == 1
            and any(request.committee_context_hash is not None for request in self.requests)
        ):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "independent round-one requests must not contain committee input",
            )
        if self.requests and self.plan.number == 2:
            committee_input_hashes = {request.committee_context_hash for request in self.requests}
            if None in committee_input_hashes or len(committee_input_hashes) != 1:
                raise DomainError(
                    DomainErrorCode.INVARIANT_VIOLATION,
                    "round-two requests must share one structured committee input hash",
                )


@dataclass(frozen=True, slots=True)
class CommitteeSessionResult:
    """The complete protocol result: exactly one independent round and one finite review round."""

    rounds: tuple[CommitteeRoundResult, CommitteeRoundResult]

    def __post_init__(self) -> None:
        if tuple(round_result.plan.number for round_result in self.rounds) != (1, 2):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "committee session must contain exactly rounds one and two in order",
            )


class CommitteeRuntime:
    """Execute only a supplied legal plan; no Decision or downstream authority is present."""

    def __init__(self, *, agent_runtime: AgentRuntime) -> None:
        self._agent_runtime = agent_runtime

    async def run_round_one(
        self, *, context: AnalysisContext, request_factory: RequestFactory
    ) -> CommitteeRoundResult:
        """Run mandatory specialists concurrently without sharing their outputs during execution."""

        return await self.run_round(
            plan=plan_round_one(),
            context=context,
            request_factory=request_factory,
            role_input=CommitteeRoleInput(context=context),
        )

    async def run_session(
        self, *, context: AnalysisContext, request_factory: RequestFactory
    ) -> CommitteeSessionResult:
        """Run the only two protocol rounds and preserve unresolved conflicts for audit."""

        round_one = await self.run_round_one(context=context, request_factory=request_factory)
        conflicts = detect_stance_conflicts(tuple(result.opinion for result in round_one.results))
        round_two = await self.run_round(
            plan=plan_round_two(conflicts),
            context=context,
            request_factory=request_factory,
            role_input=CommitteeRoleInput(
                context=context,
                visible_opinions=round_one.results,
                conflicts=conflicts,
            ),
        )
        return CommitteeSessionResult(rounds=(round_one, round_two))

    async def run_round(
        self,
        *,
        plan: CommitteeRound,
        context: AnalysisContext,
        request_factory: RequestFactory,
        role_input: CommitteeRoleInput | None = None,
    ) -> CommitteeRoundResult:
        """Execute all planned roles against exactly the supplied immutable context."""

        input_for_role = role_input or CommitteeRoleInput(context=context)
        if input_for_role.context != context:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "committee role input must use the supplied frozen AnalysisContext",
            )
        requests = tuple(request_factory(role, input_for_role) for role in plan.roles)
        if tuple(request.role for request in requests) != plan.roles:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "committee request factory must preserve planned role identities",
            )
        if any(
            request.committee_context_hash != input_for_role.content_hash for request in requests
        ):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "committee request factory must preserve the structured committee input hash",
            )
        results = await asyncio.gather(
            *(self._agent_runtime.run(request=request, context=context) for request in requests)
        )
        return CommitteeRoundResult(plan=plan, results=tuple(results), requests=requests)
