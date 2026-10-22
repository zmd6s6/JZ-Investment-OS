"""Freeze portfolio, policy and selected evidence before calling the investment team."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

from investment_os.application.analysis_execution_context import (
    AnalysisExecutionContextStore,
    ContextRecorder,
    ExecutionContextFailure,
    ExecutionContextReceipt,
    ExecutionContextView,
)
from investment_os.application.analysis_governance import (
    AnalysisStrategyCatalog,
    FrozenAnalysisPolicy,
)
from investment_os.application.analysis_inputs import AnalysisInputsPort
from investment_os.application.analysis_market import (
    AnalysisMarketConfiguration,
    AnalysisMarketFactory,
    AnalysisMarketOptions,
    AnalysisMarketPlan,
    MarketAttempt,
    MarketAttemptEvent,
    MarketAuditFailure,
    MarketAuditPort,
    MarketRecorder,
)
from investment_os.application.analysis_models import (
    AnalysisModelConfiguration,
    AnalysisModelOptions,
)
from investment_os.application.analysis_orchestrator import (
    AnalysisRequest,
    AnalysisRunResult,
    execute_analysis,
    freeze_governance,
)
from investment_os.application.analysis_progress import AnalysisCancelled, AnalysisProgress
from investment_os.application.analysis_run import AnalysisRunRead, AnalysisRunService
from investment_os.application.analysis_valuation import AnalysisValuation
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
    market_profile_ids: tuple[UUID, ...] | None = None
    market_configuration_hash: str | None = None


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
        market_configuration: AnalysisMarketConfiguration | None = None,
        market_factory: AnalysisMarketFactory | None = None,
        market_audit: MarketAuditPort | None = None,
        strategy_catalog: AnalysisStrategyCatalog | None = None,
        execution_context_store: AnalysisExecutionContextStore | None = None,
    ) -> None:
        self._inputs, self._portfolios, self._runs = inputs, portfolios, analysis_runs
        self._committee, self._market_data, self._catalog = committee, market_data, catalog
        self._policy_version_label = policy_version_label
        self._models = model_configuration
        self._markets, self._market_factory = market_configuration, market_factory
        self._market_audit = market_audit
        self._strategies = strategy_catalog
        self._execution_contexts = execution_context_store

    async def execution_context(self, run_id: UUID) -> ExecutionContextView:
        await self._runs.get(run_id)
        if self._execution_contexts is None:
            raise RuntimeError("execution context store unavailable")
        return await self._execution_contexts.read(run_id)

    async def market_events(self, run_id: UUID) -> tuple[MarketAttemptEvent, ...]:
        await self._runs.get(run_id)
        if self._market_audit is None:
            raise RuntimeError("market audit unavailable")
        return await self._market_audit.events(run_id)

    async def review_policy(self, portfolio_id: UUID | None = None) -> FrozenAnalysisPolicy:
        return await self._inputs.policy(portfolio_id, as_of=datetime.now(UTC))

    async def market_options(self) -> AnalysisMarketOptions:
        if self._markets is None:
            raise ApplicationError(
                ApplicationErrorCode.ANALYSIS_MARKET_CONFIGURATION_INVALID,
                "market configuration unavailable",
            )
        return await self._markets.options()

    async def model_options(self) -> AnalysisModelOptions:
        if self._models is None:
            raise ApplicationError(
                ApplicationErrorCode.ANALYSIS_MODEL_CONFIGURATION_INVALID,
                "model configuration unavailable",
            )
        return await self._models.options()

    async def prepare(self, inp: StartAnalysisInput) -> PreparedAnalysis:
        if self._markets is None and (
            inp.market_profile_ids is not None or inp.market_configuration_hash is not None
        ):
            raise ApplicationError(
                ApplicationErrorCode.ANALYSIS_MARKET_CONFIGURATION_INVALID,
                "market configuration unavailable",
            )
        market_plan = (
            await self._markets.freeze(inp.market_profile_ids or (), inp.market_configuration_hash)
            if self._markets
            else None
        )
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
        policy = await self._inputs.policy(inp.portfolio_id, as_of=as_of)
        governance = freeze_governance(policy)
        policy_label = policy.label
        thesis = await self._inputs.thesis(inp.instrument_id, as_of=as_of)
        selected = await self._inputs.evidence(
            inp.instrument_id, as_of=as_of, evidence_ids=inp.evidence_ids
        )
        if self._strategies is not None:
            strategy = await self._strategies.freeze(governance)
            governance = type(governance).model_validate(
                {**governance.model_dump(), "strategy": strategy, "strategy_status": "TEST_DEFAULT"}
            )
        snapshot = json.loads(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "as_of": as_of.isoformat(),
                    "instrument_id": str(inp.instrument_id),
                    "policy_version_label": policy_label,
                    "governance": governance.snapshot(),
                    "thesis": thesis.snapshot(),
                    "selection_mode": "EXPLICIT"
                    if inp.evidence_ids is not None
                    else "LEGACY_RECENT",
                    "portfolio": asdict(portfolio),
                    "evidence": [item.provenance for item in selected],
                    "model_plan": model_plan.model_dump(mode="json") if model_plan else None,
                    "market_plan": market_plan.model_dump(mode="json") if market_plan else None,
                    "market_audit_version": "1.0" if self._market_audit else None,
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
            market_plan=market_plan,
            governance=governance,
            input_snapshot_hash=snapshot["input_hash"],
            thesis=thesis,
            thesis_state=thesis.state,
            thesis_version_id=thesis.version.id if thesis.version else None,
        )
        return PreparedAnalysis(request, snapshot)

    async def execute_prepared(
        self,
        request: AnalysisRequest,
        *,
        progress: AnalysisProgress | None = None,
        market_record: MarketRecorder | None = None,
    ) -> AnalysisRunResult:
        if request.thesis is None:
            return AnalysisRunResult(
                "FAILED",
                None,
                "ANALYSIS_THESIS_SNAPSHOT_MISSING",
                "旧任务未固定投资逻辑版本, 未调用模型; 请核对后明确发起新运行。",
            )
        if (
            request.thesis.instrument_id != request.instrument_id
            or request.thesis.as_of != request.as_of
            or request.thesis.state != request.thesis_state
            or (request.thesis.version.id if request.thesis.version else None)
            != request.thesis_version_id
        ):
            return AnalysisRunResult(
                "FAILED",
                None,
                "ANALYSIS_THESIS_INVALID",
                "固定投资逻辑与运行输入不一致, 未调用模型。",
            )
        if any(
            e.freshness == "FRESH"
            and e.expires_at is not None
            and e.expires_at <= datetime.now(UTC)
            for e in request.thesis.evidence
        ):
            return AnalysisRunResult(
                "FAILED",
                None,
                "ANALYSIS_THESIS_EVIDENCE_UNAVAILABLE",
                "排队期间投资逻辑的支持资料已过期, 未调用模型; 请先核对资料再明确发起新运行。",
            )
        if request.governance is None:
            return AnalysisRunResult(
                "FAILED",
                None,
                "ANALYSIS_GOVERNANCE_SNAPSHOT_MISSING",
                "旧任务未固定政策与运行工件, 未调用模型。请核对后明确新建运行。",
            )
        if self._strategies is not None and request.governance.strategy is None:
            return AnalysisRunResult(
                "FAILED",
                None,
                "ANALYSIS_STRATEGY_SNAPSHOT_MISSING",
                "旧任务未固定独立测试策略, 未调用模型; 请核对后明确发起新运行。",
            )
        if request.governance.strategy is not None:
            try:
                if self._strategies is None:
                    raise ValueError("strategy catalog unavailable")
                await self._strategies.validate(request.governance)
            except (ApplicationError, ValueError):
                return AnalysisRunResult(
                    "FAILED",
                    None,
                    "ANALYSIS_STRATEGY_CHANGED",
                    "固定测试策略、代码或主表校验失败, 未调用模型或行情; "
                    "请核对服务版本后明确发起新运行。",
                )
        try:
            request.governance.policy.require_available(request.as_of)
            if (
                request.governance.model_copy(
                    update={"strategy": None, "strategy_status": "NOT_CONFIGURED"}
                )
                != freeze_governance(request.governance.policy)
                or request.policy_version_label != request.governance.policy.label
            ):
                raise ValueError("frozen runtime artifacts differ")
        except ValueError:
            return AnalysisRunResult(
                "FAILED",
                None,
                "ANALYSIS_GOVERNANCE_CHANGED",
                "固定的政策或运行工件校验失败, 未调用模型。请核对版本后明确新建运行。",
            )
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
        attempts: list[MarketAttempt] = []
        market_data = self._market_data
        if self._market_factory is not None:
            plan = request.market_plan or AnalysisMarketPlan()
            try:
                if self._markets is None:
                    raise ApplicationError(
                        ApplicationErrorCode.ANALYSIS_MARKET_CONFIGURATION_CHANGED,
                        "market configuration unavailable",
                    )
                await self._markets.validate(plan)
            except ApplicationError:
                return AnalysisRunResult(
                    "FAILED",
                    None,
                    "ANALYSIS_MARKET_CONFIGURATION_CHANGED",
                    "固定行情档案已修改或停用, 未调用模型或行情源。请核对后新建运行。",
                )
            if market_record is None and self._market_audit is not None and request.budget_task_id:

                async def persist(event: MarketAttemptEvent) -> None:
                    assert self._market_audit is not None and request.budget_task_id is not None
                    await self._market_audit.append(request.budget_task_id, event)

                market_record = persist
            if plan.profiles and market_record is None:
                return AnalysisRunResult(
                    "FAILED",
                    None,
                    "ANALYSIS_MARKET_AUDIT_UNAVAILABLE",
                    "行情审计不可用, 未调用模型或行情。请修复后明确新建运行。",
                )
            market_data = self._market_factory.for_plan(plan, attempts.append, market_record)
        try:
            recorder: ContextRecorder | None = None
            if request.budget_task_id is not None:
                if self._execution_contexts is None:
                    raise ExecutionContextFailure("execution context store unavailable")

                async def record_context(value: AnalysisValuation) -> ExecutionContextReceipt:
                    assert (
                        self._execution_contexts is not None and request.budget_task_id is not None
                    )
                    try:
                        return await self._execution_contexts.save(
                            request.budget_task_id,
                            value,
                            worker_token=request.execution_lease,
                        )
                    except AnalysisCancelled:
                        raise
                    except Exception:
                        raise ExecutionContextFailure("execution context commit failed") from None

                recorder = record_context
            result = await execute_analysis(
                request,
                committee=self._committee,
                market_data=market_data,
                progress=progress,
                context_recorder=recorder,
            )
        except ExecutionContextFailure:
            return AnalysisRunResult(
                "FAILED",
                None,
                "ANALYSIS_CONTEXT_RECORDING_FAILED",
                "模型前上下文存储未装配, 未调用模型。请检查服务配置, 不需要更换令牌。",
            )
        except MarketAuditFailure:
            return AnalysisRunResult(
                "FAILED",
                None,
                "ANALYSIS_MARKET_AUDIT_UNAVAILABLE",
                "行情记录保存失败, 已停止继续读取。已发请求可能计费; 请核对调用记录与供应商费用。",
            )
        if result.payload is not None and self._market_factory is not None:
            result = replace(
                result,
                payload=replace(
                    result.payload,
                    valuation={
                        **result.payload.valuation,
                        "market_data": {
                            "selection": "ORDERED"
                            if request.market_plan and request.market_plan.profiles
                            else "NONE",
                            "attempts": [a.model_dump(mode="json") for a in attempts],
                        },
                    },
                ),
            )
        return result

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
        try:
            return await self._runs.finish(
                running_id,
                status="SUCCEEDED",
                payload={**result.payload.to_dict(), "input_snapshot": snapshot},
                research=getattr(result, "research", None),
            )
        except Exception:
            return await self._runs.finish(
                running_id,
                status="FAILED",
                payload={"input_snapshot": snapshot},
                failure_code="ANALYSIS_RECORDING_FAILED",
                failure_detail=(
                    "研究记录未能原子保存, 未发布成功报告, 不自动重放模型。请核对运行与费用。"
                ),
            )
