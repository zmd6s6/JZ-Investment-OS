"""Explicit single-candidate research, preserving the frozen funnel origin."""

from typing import Literal, Protocol
from uuid import UUID

from investment_os.application.analysis_runs import (
    AnalysisDto,
    AnalysisRunView,
    AnalysisStart,
    analysis_command_payload,
)
from investment_os.application.opportunities import FunnelRun, OpportunityError
from investment_os.application.portfolio_valuation import fingerprint


class CandidateResearchStart(AnalysisDto):
    schema_version: Literal["1.0"] = "1.0"
    funnel_run_id: UUID
    analysis: AnalysisStart


class CandidateResearchView(AnalysisDto):
    command: CandidateResearchStart
    analysis_run: AnalysisRunView | None
    status: Literal["AWAITING_EXPLICIT_RETRY", "ANALYSIS_RECORDED"]
    auto_trade: Literal[False] = False


class FunnelReader(Protocol):
    async def get_run(self, run_id: UUID) -> FunnelRun | None: ...


class CandidateResearchStore(Protocol):
    async def record(self, command: CandidateResearchStart) -> CandidateResearchStart: ...
    async def list_for(self, funnel_run_id: UUID) -> tuple[CandidateResearchStart, ...]: ...


class CandidateAnalysisStarter(Protocol):
    async def start(self, command: AnalysisStart) -> AnalysisRunView: ...


class CandidateAnalysisReader(Protocol):
    async def find_request(self, request_id: UUID) -> AnalysisRunView | None: ...


class OpportunityResearchService:
    def __init__(
        self,
        funnels: FunnelReader,
        intents: CandidateResearchStore,
        start: CandidateAnalysisStarter,
        analyses: CandidateAnalysisReader,
    ):
        self._funnels = funnels
        self._intents = intents
        self._start = start
        self._analyses = analyses

    async def start(self, command: CandidateResearchStart) -> CandidateResearchView:
        funnel = await self._funnels.get_run(command.funnel_run_id)
        if funnel is None:
            raise OpportunityError("FUNNEL_RUN_NOT_FOUND")
        target = command.analysis.instrument_id
        if target not in funnel.candidate_ids:
            raise OpportunityError("NOT_A_BOUNDED_CANDIDATE")
        row = next(row for row in funnel.rows if row.instrument_id == target)
        if (
            not row.candidate
            or len(funnel.candidate_ids) > min(20, funnel.query.candidate_limit)
            or not set(row.evidence_ids) <= set(command.analysis.evidence_ids)
            or command.analysis.market_source_name != funnel.query.quote_source_name
        ):
            raise OpportunityError("CANDIDATE_INPUT_MISMATCH")
        # A caller cannot attach this origin to an unrelated pre-existing request.
        existing = await self._analyses.find_request(command.analysis.request_id)
        if existing and existing.request_hash != fingerprint(
            analysis_command_payload(command.analysis)
        ):
            raise OpportunityError("REQUEST_CONTENT_CONFLICT")
        self._view(command, existing)
        # Record the exact explicit request BEFORE queueing. This event is not a worker job.
        # If queueing fails or the response is lost, the same request can be explicitly retried;
        # the Analysis request id provides exactly-once queueing, never automatic paid replay.
        await self._intents.record(command)
        run = await self._start.start(command.analysis)
        return self._view(command, run)

    @staticmethod
    def _view(
        command: CandidateResearchStart, run: AnalysisRunView | None
    ) -> CandidateResearchView:
        if run is not None and (
            run.request_id != command.analysis.request_id
            or run.request_hash != fingerprint(analysis_command_payload(command.analysis))
            or run.instrument_id != command.analysis.instrument_id
            or run.portfolio_id != command.analysis.portfolio_id
        ):
            raise OpportunityError("CANDIDATE_ANALYSIS_MISMATCH")
        return CandidateResearchView(
            command=command,
            analysis_run=run,
            status="ANALYSIS_RECORDED" if run else "AWAITING_EXPLICIT_RETRY",
        )

    async def list_for(self, funnel_run_id: UUID) -> tuple[CandidateResearchView, ...]:
        commands = await self._intents.list_for(funnel_run_id)
        return tuple(
            [
                self._view(command, await self._analyses.find_request(command.analysis.request_id))
                for command in commands
            ]
        )
