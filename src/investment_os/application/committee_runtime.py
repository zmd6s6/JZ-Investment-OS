"""Concurrent, bounded execution of a committee round against one frozen context."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from investment_os.application.agent_runtime import AgentRunResult, AgentRuntime
from investment_os.application.analysis_context import AnalysisContext
from investment_os.application.committee import (
    CommitteeRound,
    detect_stance_conflicts,
    plan_round_one,
    plan_round_two,
)
from investment_os.application.llm_gateway import LLMGatewayRequest
from investment_os.domain.agent import AgentRole
from investment_os.domain.errors import DomainError, DomainErrorCode

RequestFactory = Callable[[AgentRole, AnalysisContext], LLMGatewayRequest]


@dataclass(frozen=True, slots=True)
class CommitteeRoundResult:
    """Ordered, explicit role outcomes from exactly one legal committee round."""

    plan: CommitteeRound
    results: tuple[AgentRunResult, ...]

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
        )
        return CommitteeSessionResult(rounds=(round_one, round_two))

    async def run_round(
        self,
        *,
        plan: CommitteeRound,
        context: AnalysisContext,
        request_factory: RequestFactory,
    ) -> CommitteeRoundResult:
        """Execute all planned roles against exactly the supplied immutable context."""

        requests = tuple(request_factory(role, context) for role in plan.roles)
        if tuple(request.role for request in requests) != plan.roles:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "committee request factory must preserve planned role identities",
            )
        results = await asyncio.gather(
            *(self._agent_runtime.run(request=request, context=context) for request in requests)
        )
        return CommitteeRoundResult(plan=plan, results=tuple(results))
