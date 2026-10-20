"""Explicitly submitted durable analysis jobs, with no automatic paid retries."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from investment_os.application.analysis_orchestrator import AnalysisRequest, AnalysisRunResult
from investment_os.application.analysis_product import (
    PreparedAnalysis,
    ProductAnalysisService,
    StartAnalysisInput,
)
from investment_os.application.analysis_progress import AnalysisProgress, AnalysisStage, StageState
from investment_os.application.analysis_run import AnalysisRunRead
from investment_os.application.research_preview import content_hash


class AnalysisWorkItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    request: AnalysisRequest


class AnalysisJobError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AnalysisProgressEvent:
    id: UUID
    run_id: UUID
    sequence: int
    stage: AnalysisStage
    state: StageState
    occurred_at: datetime


ExecuteJob = Callable[[AnalysisRequest, AnalysisProgress], Awaitable[AnalysisRunResult]]


class AnalysisJobsPort(Protocol):
    async def submit(
        self,
        request_id: UUID,
        request_hash: str,
        prepare: Callable[[], Awaitable[PreparedAnalysis]],
        *,
        retry_of: UUID | None,
    ) -> AnalysisRunRead: ...

    async def events(self, run_id: UUID) -> tuple[AnalysisProgressEvent, ...]: ...
    async def cancel(self, run_id: UUID) -> AnalysisRunRead: ...
    async def retry_input(self, run_id: UUID) -> StartAnalysisInput: ...
    async def work_once(self, execute: ExecuteJob) -> bool: ...


class AnalysisJobService:
    def __init__(self, port: AnalysisJobsPort, product: ProductAnalysisService) -> None:
        self._port, self._product = port, product

    async def submit(
        self,
        request_id: UUID,
        inp: StartAnalysisInput,
        *,
        retry_of: UUID | None = None,
    ) -> AnalysisRunRead:
        digest = content_hash(
            [
                str(inp.instrument_id),
                str(inp.portfolio_id),
                inp.source,
                sorted(str(i) for i in inp.evidence_ids) if inp.evidence_ids is not None else None,
                str(retry_of) if retry_of else None,
            ]
            + (
                [
                    str(inp.model_profile_id) if inp.model_profile_id else None,
                    inp.model_configuration_hash,
                ]
                if inp.model_profile_id is not None or inp.model_configuration_hash is not None
                else []
            )
            + (
                [
                    {
                        "market_profile_ids": [str(i) for i in inp.market_profile_ids]
                        if inp.market_profile_ids is not None
                        else None,
                        "market_configuration_hash": inp.market_configuration_hash,
                    }
                ]
                if inp.market_profile_ids is not None or inp.market_configuration_hash is not None
                else []
            )
        )
        return await self._port.submit(
            request_id,
            digest,
            lambda: self._product.prepare(inp),
            retry_of=retry_of,
        )

    async def events(self, run_id: UUID) -> tuple[AnalysisProgressEvent, ...]:
        return await self._port.events(run_id)

    async def cancel(self, run_id: UUID) -> AnalysisRunRead:
        return await self._port.cancel(run_id)

    async def retry(self, run_id: UUID, request_id: UUID) -> AnalysisRunRead:
        return await self.submit(request_id, await self._port.retry_input(run_id), retry_of=run_id)

    async def run_once(self) -> bool:
        async def execute(
            request: AnalysisRequest, progress: AnalysisProgress
        ) -> AnalysisRunResult:
            return await self._product.execute_prepared(request, progress=progress)

        return await self._port.work_once(execute)
