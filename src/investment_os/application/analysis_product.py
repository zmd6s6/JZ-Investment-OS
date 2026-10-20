"""Freeze portfolio, policy and selected evidence before calling the investment team."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

from investment_os.application.analysis_inputs import AnalysisInputsPort
from investment_os.application.analysis_models import (
    AnalysisModelConfiguration,
    AnalysisModelOptions,
)
from investment_os.application.analysis_orchestrator import (
    AnalysisRequest,
    AnalysisRunResult,
    execute_analysis,
)
from investment_os.application.analysis_progress import AnalysisProgress
from investment_os.application.analysis_run import AnalysisRunRead, AnalysisRunService
from investment_os.application.committee_runtime import CommitteeRuntime
from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.instrument_catalog import InstrumentCatalogPort
from investment_os.application.market_data import MarketDataPort
from investment_os.application.portfolio_book import PortfolioBookService
from investment_os.application.research_preview import content_hash


@dataclass(frozen=True, slots=True)
class StartAnalysisInput:
    instrument_id: UUID
    portfolio_id: UUID
    source: str = "PORTFOLIO"
    as_of: datetime | None = None
    evidence_ids: tuple[UUID, ...] | None = None
    model_profile_id: UUID | None = None
    model_configuration_hash: str | None = None


@dataclass(frozen=True, slots=True)
class PreparedAnalysis:
    request: AnalysisRequest
    snapshot: dict[str, object]


class ProductAnalysisService:
    def __init__(
        self,
        *,
        inputs: AnalysisInputsPort,
        portfolios: PortfolioBookService,
        analysis_runs: AnalysisRunService,
        committee: CommitteeRuntime,
        market_data: MarketDataPort,
        catalog: InstrumentCatalogPort | None = None,
        policy_version_label: str = "TEST_DEFAULT",
        model_configuration: AnalysisModelConfiguration | None = None,
    ) -> None:
        self._inputs, self._portfolios, self._runs = inputs, portfolios, analysis_runs
        self._committee, self._market_data, self._catalog = committee, market_data, catalog
        self._policy_version_label = policy_version_label
        self._models = model_configuration

    async def model_options(self) -> AnalysisModelOptions:
        if self._models is None:
            raise ApplicationError(
                ApplicationErrorCode.ANALYSIS_MODEL_CONFIGURATION_INVALID,
                "model configuration unavailable",
            )
        return await self._models.options()

    async def prepare(self, inp: StartAnalysisInput) -> PreparedAnalysis:
        if self._models is None and (
            inp.model_profile_id is not None or inp.model_configuration_hash is not None
        ):
            raise ApplicationError(
                ApplicationErrorCode.ANALYSIS_MODEL_CONFIGURATION_INVALID,
                "model configuration unavailable",
            )
        model_plan = (
            await self._models.freeze(inp.model_profile_id, inp.model_configuration_hash)
            if self._models
            else None
        )
        portfolio = await self._portfolios.get_portfolio(inp.portfolio_id)
        if portfolio is None:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_NOT_FOUND, "portfolio not found for analysis"
            )
        as_of = inp.as_of or datetime.now(UTC)
        if as_of.tzinfo is None:
            raise ApplicationError(
                ApplicationErrorCode.ANALYSIS_EVIDENCE_SELECTION_INVALID,
                "analysis time must be aware",
            )
        policy_label = await self._inputs.policy_label(self._policy_version_label)
        selected = await self._inputs.evidence(
            inp.instrument_id, as_of=as_of, evidence_ids=inp.evidence_ids
        )
        snapshot = json.loads(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "as_of": as_of.isoformat(),
                    "instrument_id": str(inp.instrument_id),
                    "policy_version_label": policy_label,
                    "selection_mode": "EXPLICIT"
                    if inp.evidence_ids is not None
                    else "LEGACY_RECENT",
                    "portfolio": asdict(portfolio),
                    "evidence": [item.provenance for item in selected],
                    "model_plan": model_plan.model_dump(mode="json") if model_plan else None,
                },
                default=str,
            )
        )
        snapshot["input_hash"] = content_hash(snapshot)
        pos = next((p for p in portfolio.positions if p.instrument_id == inp.instrument_id), None)
        if pos is not None:
            market, symbol, currency = pos.market, pos.symbol, pos.currency
        else:
            entry = await self._catalog.get(inp.instrument_id) if self._catalog else None
            market, symbol = (entry.market, entry.symbol) if entry else ("", "")
            currency = entry.currency if entry else portfolio.base_currency
        request = AnalysisRequest(
            instrument_id=inp.instrument_id,
            portfolio_id=inp.portfolio_id,
            portfolio=portfolio,
            as_of=as_of,
            policy_version_label=policy_label,
            evidence=tuple(item.source for item in selected),
            source=inp.source,
            instrument_market=market,
            instrument_symbol=symbol,
            instrument_currency=currency or portfolio.base_currency,
            model_plan=model_plan,
        )
        return PreparedAnalysis(request, snapshot)

    async def execute_prepared(
        self,
        request: AnalysisRequest,
        *,
        progress: AnalysisProgress | None = None,
    ) -> AnalysisRunResult:
        if self._models is not None and request.model_plan is None:
            return AnalysisRunResult(
                status="FAILED",
                payload=None,
                failure_code="ANALYSIS_MODEL_CONFIGURATION_MISSING",
                failure_detail="旧任务未固定模型配置, 未自动调用当前模型。请核对后明确新建运行。",
            )
        if request.model_plan is not None:
            try:
                if self._models is None:
                    raise ApplicationError(
                        ApplicationErrorCode.ANALYSIS_MODEL_CONFIGURATION_CHANGED,
                        "frozen models cannot be verified",
                    )
                await self._models.validate(request.model_plan)
            except ApplicationError:
                return AnalysisRunResult(
                    status="FAILED",
                    payload=None,
                    failure_code="ANALYSIS_MODEL_CONFIGURATION_CHANGED",
                    failure_detail=(
                        "本次固定的模型档案已修改、停用或不可用; "
                        "未自动换用模型。请核对设置后明确新建运行。"
                    ),
                )
        return await execute_analysis(
            request,
            committee=self._committee,
            market_data=self._market_data,
            **({"progress": progress} if progress is not None else {}),
        )

    async def start(self, inp: StartAnalysisInput) -> AnalysisRunRead:
        prepared = await self.prepare(inp)
        request, snapshot = prepared.request, prepared.snapshot
        running_id = await self._runs.mark_running(
            instrument_id=inp.instrument_id,
            portfolio_id=inp.portfolio_id,
            source=inp.source,
            as_of=request.as_of,
            policy_version_label=request.policy_version_label,
            input_snapshot=snapshot,
        )
        result = await self.execute_prepared(replace(request, budget_task_id=running_id))
        if result.status != "SUCCEEDED" or result.payload is None:
            return await self._runs.finish(
                running_id,
                status="FAILED",
                payload={"stage": "FAILED", "input_snapshot": snapshot},
                failure_code=result.failure_code or "ANALYSIS_FAILED",
                failure_detail=result.failure_detail or "分析失败",
            )
        return await self._runs.finish(
            running_id,
            status="SUCCEEDED",
            payload={**result.payload.to_dict(), "input_snapshot": snapshot},
        )
