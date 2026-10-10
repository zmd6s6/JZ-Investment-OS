"""Load inputs and run one analysis for a portfolio/watchlist instrument."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.analysis_orchestrator import (
    AnalysisEvidenceSource,
    AnalysisRequest,
    AnalysisRunResult,
    execute_analysis,
)
from investment_os.application.analysis_run import AnalysisRunRead, AnalysisRunService
from investment_os.application.committee_runtime import CommitteeRuntime
from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.market_data import MarketDataPort
from investment_os.application.portfolio_book import PortfolioBookService
from investment_os.infrastructure.persistence.models import EvidenceRecord


@dataclass(frozen=True, slots=True)
class StartAnalysisInput:
    instrument_id: UUID
    portfolio_id: UUID
    source: str = "PORTFOLIO"
    as_of: datetime | None = None


class ProductAnalysisService:
    """Compose portfolio + evidence + committee + market data into one persisted run."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        portfolios: PortfolioBookService,
        analysis_runs: AnalysisRunService,
        committee: CommitteeRuntime,
        market_data: MarketDataPort,
        policy_version_label: str = "TEST_DEFAULT",
    ) -> None:
        self._session_factory = session_factory
        self._portfolios = portfolios
        self._runs = analysis_runs
        self._committee = committee
        self._market_data = market_data
        self._policy_version_label = policy_version_label

    async def start(self, inp: StartAnalysisInput) -> AnalysisRunRead:
        portfolio = await self._portfolios.get_portfolio(inp.portfolio_id)
        if portfolio is None:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_NOT_FOUND,
                "portfolio not found for analysis",
            )
        as_of = inp.as_of or datetime.now().astimezone()
        if as_of.tzinfo is None:
            from datetime import UTC

            as_of = as_of.replace(tzinfo=UTC)

        async with self._session_factory() as session:
            statement = (
                select(EvidenceRecord)
                .where(
                    EvidenceRecord.instrument_id == inp.instrument_id,
                    EvidenceRecord.available_at <= as_of,
                )
                .order_by(EvidenceRecord.observed_at.desc())
                .limit(50)
            )
            evidence_rows = list((await session.scalars(statement)).all())

        evidence = tuple(
            AnalysisEvidenceSource(
                evidence_id=row.id,
                content_hash=row.content_hash,
                available_at=row.available_at,
                source_tier=row.source_tier,
            )
            for row in evidence_rows
        )

        request = AnalysisRequest(
            instrument_id=inp.instrument_id,
            portfolio_id=inp.portfolio_id,
            portfolio=portfolio,
            as_of=as_of,
            policy_version_label=self._policy_version_label,
            evidence=evidence,
            source=inp.source,
        )

        result: AnalysisRunResult = await execute_analysis(
            request,
            committee=self._committee,
            market_data=self._market_data,
        )

        if result.status != "SUCCEEDED" or result.payload is None:
            return await self._runs.record_failure(
                instrument_id=inp.instrument_id,
                portfolio_id=inp.portfolio_id,
                source=inp.source,
                as_of=as_of,
                policy_version_label=self._policy_version_label,
                failure_code=result.failure_code or "ANALYSIS_FAILED",
                failure_detail=result.failure_detail or "分析失败",
            )

        return await self._runs.record_success(
            instrument_id=result.payload.instrument_id,
            portfolio_id=result.payload.portfolio_id,
            source=result.payload.source,
            as_of=as_of,
            policy_version_label=result.payload.policy_version_label,
            payload=result.payload.to_dict(),
        )
