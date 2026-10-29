"""Actual PG, canonical artifacts, gateway/Worker and source qualification boundaries."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from analysis_fixture import model_output
from analysis_numeric_fixture import seed_numeric
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_analysis_pipeline import SyntheticSecrets

from investment_os.application.analysis_configuration import AnalysisStartService
from investment_os.application.analysis_runs import ANALYSIS_ROLES, AnalysisStart
from investment_os.application.instrument_catalog import InstrumentCatalogService
from investment_os.application.investment_analysis import InvestmentAnalysisOrchestrator
from investment_os.application.llm_budget import LLMBudgetPolicy, LLMBudgetService
from investment_os.application.portfolio_valuation import PortfolioValuationService
from investment_os.application.provider_settings import ProviderSettingsService
from investment_os.application.research_runtime import (
    DataProviderRuntimeRegistry,
    ResearchProviderRuntime,
)
from investment_os.infrastructure.analysis_execution import SqlAnalysisExecution
from investment_os.infrastructure.analysis_inputs import (
    AnalysisGatewayFactory,
    SqlAnalysisInputPreparer,
)
from investment_os.infrastructure.analysis_risk_sizing import (
    SqlAnalysisRiskSizing,
    SqlNumericSources,
)
from investment_os.infrastructure.analysis_risk_sizing_models import (
    AnalysisRiskResultRecord,
    AnalysisSizingResultRecord,
)
from investment_os.infrastructure.analysis_runs import SqlAnalysisRuns
from investment_os.infrastructure.catalog_portfolio import SessionCatalogPort
from investment_os.infrastructure.evidence_ingestion import SqlAlchemyEvidenceIngestor
from investment_os.infrastructure.llm_budget import SqlAlchemyLLMBudgetStore
from investment_os.infrastructure.manual_market_data import SqlManualMarketData
from investment_os.infrastructure.persistence.models import (
    InvestmentDecisionRecord,
    PositionSizingRunRecord,
    RiskAssessmentRecord,
)
from investment_os.infrastructure.portfolio_valuation import SqlValuationInputs
from investment_os.infrastructure.provider_settings import SqlAlchemyProviderSettingsStore
from investment_os.worker.analysis_runner import AnalysisWorkerRunner

pytestmark = pytest.mark.integration


async def pipeline(
    engine, *, candidate_action="ADD", bucket="CORE", clock=None, on_request=None, **seed_options
):
    ids, source = await seed_numeric(engine, **seed_options)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    secrets = SyntheticSecrets()
    providers = ProviderSettingsService(SqlAlchemyProviderSettingsStore(sessions), secrets)
    profile = await providers.save_model_profile(
        profile_id=None,
        name="205明确合成模型",
        provider_type="OPENAI_COMPATIBLE",
        base_url="http://127.0.0.1:1/v1",
        model_name="synthetic-205",
        timeout_seconds=5,
        max_tokens=1000,
        enabled=True,
        credential="synthetic-205-only",
        pricing_version="synthetic-205",
        pricing_currency="CNY",
        input_token_price=Decimal(0),
        output_token_price=Decimal(0),
        pricing_effective_at=datetime.now(UTC),
    )
    budget = LLMBudgetService(SqlAlchemyLLMBudgetStore(sessions))
    await budget.save_policy(
        LLMBudgetPolicy("synthetic-205", "CNY", 2000000, 4000000, Decimal(1), Decimal(2))
    )
    store = SqlAnalysisRuns(sessions)
    service = AnalysisStartService(
        store,
        PortfolioValuationService(SqlValuationInputs(sessions), SqlManualMarketData(sessions)),
        providers,
        budget,
        InstrumentCatalogService(SessionCatalogPort(sessions)),
    )
    calls = []

    async def respond(request):
        wrapper = json.loads(json.loads(request.content)["messages"][1]["content"])
        calls.append(wrapper)
        if on_request is not None:
            await on_request(wrapper)
        output = model_output(wrapper)
        if wrapper["role"] == "CIO":
            output["proposed_action"] = candidate_action
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(output)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    execution = SqlAnalysisExecution(
        sessions,
        SqlAnalysisInputPreparer(
            sessions,
            store,
            providers,
            ResearchProviderRuntime(
                provider_settings=providers,
                secret_store=secrets,
                registry=DataProviderRuntimeRegistry({}),
            ),
            SqlAlchemyEvidenceIngestor(sessions, now=lambda: datetime.now(UTC)),
        ),
        AnalysisGatewayFactory(providers, secrets, budget, store, client=client),
    )
    runner = AnalysisWorkerRunner(
        store,
        InvestmentAnalysisOrchestrator(
            store,
            execution,
            risk_sizing=SqlAnalysisRiskSizing(sessions, **({"now": clock} if clock else {})),
        ),
    )
    command = AnalysisStart(
        request_id=uuid4(),
        portfolio_id=ids["portfolio"],
        instrument_id=ids["instrument"],
        model_profiles={role: profile.id for role in ANALYSIS_ROLES},
        evidence_ids=(ids["evidence"],),
        numeric_snapshot_id=ids["snapshot"],
        position_bucket=bucket,
        market_source_name="synthetic-205-reference",
        allow_model_calls=True,
    )
    return sessions, service, store, runner, command, calls, client, source


async def test_complete_numeric_pipeline_persists_real_risk_sizing_and_never_bridges_approval(
    database_engine,
):
    sessions, service, store, runner, command, calls, client, source = await pipeline(
        database_engine
    )
    try:
        assert (
            await SqlNumericSources(sessions).get(source.snapshot_id)
        ).content_hash == source.content_hash
        queued = await service.start(command)
        await runner.dispatch_due()
        run = await store.get(queued.run_id)
        assert run.error_code is None, run.model_dump(mode="json")
        assert len(calls) == 9
        assert run.risk_sizing is not None
        assert run.risk_sizing.risk_gate == "PASS", run.risk_sizing.model_dump(mode="json")
        assert run.risk_sizing.sizing_status == "COMPUTED"
        assert run.risk_sizing.target_quantity == Decimal(500)
        assert run.risk_sizing.delta_quantity == Decimal(400)
        assert run.risk_sizing.numbers["nav"] == "100000.000000000000000000"
        assert run.shadow_decision.execution_allowed is run.shadow_decision.auto_trade is False
        assert run.shadow_decision.action.value not in {"BUY", "ADD"}
        assert run.shadow_decision.sizing_run_id == run.risk_sizing.sizing_run_id
        async with sessions() as session:
            for model in (
                RiskAssessmentRecord,
                PositionSizingRunRecord,
                AnalysisRiskResultRecord,
                AnalysisSizingResultRecord,
            ):
                assert await session.scalar(select(func.count()).select_from(model)) == 1
            assert (
                await session.scalar(select(func.count()).select_from(InvestmentDecisionRecord))
                == 0
            )
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "options",
    [
        {"source_kind": "REFERENCE_ONLY"},
        {"policy_active": False},
        {"approved": False},
        {"missing_rules": True},
        {"source_expired": True},
        {"missing_metric": "REFERENCE_PRICE"},
        {"missing_metric": "VOLATILITY"},
        {"missing_metric": "LIQUIDITY_CAPACITY"},
        {"missing_metric": "RISK_BUDGET_CAPACITY"},
        {"missing_metric": "CORRELATION"},
        {"currency": "USD"},
        {"missing_relation": True},
        {"corrupt_source": True},
    ],
)
async def test_ineligible_numeric_chain_never_persists_pass_or_quantity(database_engine, options):
    sessions, service, store, runner, command, _calls, client, _source = await pipeline(
        database_engine, **options
    )
    try:
        queued = await service.start(command)
        await runner.dispatch_due()
        run = await store.get(queued.run_id)
        assert run.error_code is None, run.model_dump(mode="json")
        assert run.risk_sizing.risk_gate == "UNKNOWN"
        assert run.risk_sizing.sizing_status == "BLOCKED"
        assert run.risk_sizing.blockers
        assert run.risk_sizing.target_quantity is None
        async with sessions() as session:
            for model in (RiskAssessmentRecord, PositionSizingRunRecord, InvestmentDecisionRecord):
                assert await session.scalar(select(func.count()).select_from(model)) == 0
    finally:
        await client.aclose()


async def test_risk_veto_does_not_create_exposure_increase_sizing(database_engine):
    sessions, service, store, runner, command, _calls, client, _source = await pipeline(
        database_engine, liquidity="0"
    )
    try:
        queued = await service.start(command)
        await runner.dispatch_due()
        run = await store.get(queued.run_id)
        assert run.error_code is None, run.model_dump(mode="json")
        assert run.risk_sizing.risk_gate == "VETO"
        assert run.risk_sizing.sizing_status == "BLOCKED"
        assert "RISK_VETO_NO_EXPOSURE_INCREASE" in run.risk_sizing.blockers
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(PositionSizingRunRecord)) == 0
            )
    finally:
        await client.aclose()


@pytest.mark.parametrize("phase", ["RISK", "CIO"])
@pytest.mark.parametrize("offset", [-1, 0, 1], ids=["just-before", "exact-expiry", "just-after"])
async def test_event_paused_stage_rechecks_actual_evaluation_time(database_engine, phase, offset):
    paused, resume = asyncio.Event(), asyncio.Event()
    clock_value = [datetime.now(UTC)]

    async def pause(wrapper):
        if wrapper["role"] == phase:
            paused.set()
            await resume.wait()

    sessions, service, store, runner, command, _calls, client, source = await pipeline(
        database_engine,
        clock=lambda: clock_value[0],
        on_request=pause,
    )
    try:
        queued = await service.start(command)
        task = asyncio.create_task(runner.dispatch_due())
        await asyncio.wait_for(paused.wait(), timeout=10)
        clock_value[0] = source.expires_at + timedelta(microseconds=offset)
        resume.set()
        await asyncio.wait_for(task, timeout=10)
        run = await store.get(queued.run_id)
        assert run.error_code is None, run.model_dump(mode="json")
        view = run.risk_sizing
        assert view.sizing_status == ("COMPUTED" if offset < 0 else "BLOCKED")
        async with sessions() as session:
            assert await session.scalar(
                select(func.count()).select_from(PositionSizingRunRecord)
            ) == (1 if offset < 0 else 0)
            assert (
                await session.scalar(select(func.count()).select_from(InvestmentDecisionRecord))
                == 0
            )
            if offset >= 0 and phase == "RISK":
                assert view.risk_gate == "UNKNOWN"
                assert (
                    await session.scalar(select(func.count()).select_from(RiskAssessmentRecord))
                    == 0
                )
            if offset >= 0 and phase == "CIO":
                assert "RISK_EXPIRED_BEFORE_SIZING" in view.blockers
    finally:
        resume.set()
        await client.aclose()


@pytest.mark.parametrize("action", ["REDUCE", "EXIT"])
async def test_veto_still_allows_deterministic_reduction_without_order(database_engine, action):
    _sessions, service, store, runner, command, _calls, client, _source = await pipeline(
        database_engine, liquidity="0", candidate_action=action
    )
    try:
        queued = await service.start(command)
        await runner.dispatch_due()
        run = await store.get(queued.run_id)
        assert run.error_code is None, run.model_dump(mode="json")
        assert run.risk_sizing.risk_gate == "VETO"
        assert run.risk_sizing.sizing_status == "COMPUTED"
        assert run.risk_sizing.delta_quantity == Decimal(-100)
        assert run.shadow_decision.execution_allowed is False
    finally:
        await client.aclose()


async def test_tactical_measurement_does_not_resize_core(database_engine):
    _sessions, service, store, runner, command, _calls, client, _source = await pipeline(
        database_engine, bucket="TACTICAL"
    )
    try:
        queued = await service.start(command)
        await runner.dispatch_due()
        run = await store.get(queued.run_id)
        assert run.error_code is None, run.model_dump(mode="json")
        assert run.risk_sizing.bucket == "TACTICAL"
        assert run.risk_sizing.target_quantity == Decimal(500)
        assert run.risk_sizing.delta_quantity == Decimal(300)
        assert Decimal(run.risk_sizing.numbers["core_weight"]) == Decimal("0.01")
        assert Decimal(run.risk_sizing.numbers["tactical_weight"]) == Decimal("0.02")
    finally:
        await client.aclose()
