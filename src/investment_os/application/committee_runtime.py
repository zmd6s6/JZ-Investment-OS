"""Concurrent, bounded execution of a committee round against one frozen context."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from investment_os.application.agent_runtime import AgentRunResult, AgentRuntime
from investment_os.application.analysis_context import AnalysisContext
from investment_os.application.committee import CommitteeRound, plan_round_one
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
