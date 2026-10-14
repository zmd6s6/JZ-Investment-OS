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
from investment_os.application.instrument_catalog import InstrumentCatalogPort
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
        catalog: InstrumentCatalogPort | None = None,
        policy_version_label: str = "TEST_DEFAULT",
    ) -> None:
        self._session_factory = session_factory
        self._portfolios = portfolios
        self._runs = analysis_runs
        self._committee = committee
        self._market_data = market_data
        self._catalog = catalog
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

        policy_label = await self._load_policy_label()

        async with self._session_factory() as session:
            statement = (
                select(EvidenceRecord)
                .where(
                    EvidenceRecord.instrument_id == inp.instrument_id,
                    EvidenceRecord.available_at <= as_of,
                    (EvidenceRecord.expires_at.is_(None) | (EvidenceRecord.expires_at > as_of)),
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
                summary=_evidence_summary(row),
                payload_excerpt=_evidence_excerpt(row),
            )
            for row in evidence_rows
        )

        pos = next(
            (p for p in portfolio.positions if p.instrument_id == inp.instrument_id),
            None,
        )
        if pos is not None:
            market, symbol, currency = pos.market, pos.symbol, pos.currency
        else:
            catalog_entry = await self._catalog.get(inp.instrument_id) if self._catalog else None
            if catalog_entry is None:
                market = symbol = ""
                currency = portfolio.base_currency
            else:
                market = catalog_entry.market
                symbol = catalog_entry.symbol
                currency = catalog_entry.currency

        request = AnalysisRequest(
            instrument_id=inp.instrument_id,
            portfolio_id=inp.portfolio_id,
            portfolio=portfolio,
            as_of=as_of,
            policy_version_label=policy_label,
            evidence=evidence,
            source=inp.source,
            instrument_market=market,
            instrument_symbol=symbol,
            instrument_currency=currency or portfolio.base_currency,
        )

        running_id = await self._runs.mark_running(
            instrument_id=inp.instrument_id,
            portfolio_id=inp.portfolio_id,
            source=inp.source,
            as_of=as_of,
            policy_version_label=policy_label,
        )

        result: AnalysisRunResult = await execute_analysis(
            request,
            committee=self._committee,
            market_data=self._market_data,
        )

        if result.status != "SUCCEEDED" or result.payload is None:
            return await self._runs.finish(
                running_id,
                status="FAILED",
                payload={"stage": "FAILED"},
                failure_code=result.failure_code or "ANALYSIS_FAILED",
                failure_detail=result.failure_detail or "分析失败",
            )

        return await self._runs.finish(
            running_id,
            status="SUCCEEDED",
            payload=result.payload.to_dict(),
        )

    async def _load_policy_label(self) -> str:
        """Pin the active policy version label; fall back to configured default."""

        from investment_os.infrastructure.persistence.models import (
            InvestmentPolicyRecord,
            InvestmentPolicyVersionRecord,
        )

        async with self._session_factory() as session:
            statement = (
                select(InvestmentPolicyRecord)
                .where(InvestmentPolicyRecord.status == "ACTIVE")
                .order_by(InvestmentPolicyRecord.created_at.desc())
                .limit(1)
            )
            policy = (await session.scalars(statement)).first()
            if policy is None or policy.current_version_id is None:
                return self._policy_version_label
            version = await session.get(InvestmentPolicyVersionRecord, policy.current_version_id)
            if version is None:
                return f"{policy.name}@{policy.version}"
            return f"{policy.name}@{version.version}"


def _evidence_summary(row: object) -> str:
    payload = getattr(row, "payload_json", None) or {}
    if isinstance(payload, dict):
        for key in ("headline", "title", "summary", "text", "content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:300]
        # fall back to first string field
        for value in payload.values():
            if isinstance(value, str) and value.strip():
                return value.strip()[:300]
    return str(getattr(row, "source_locator", ""))[:300]


def _evidence_excerpt(row: object) -> str:
    payload = getattr(row, "payload_json", None) or {}
    try:
        import json

        return json.dumps(payload, ensure_ascii=False, default=str)[:1500]
    except Exception:
        return ""
