"""Actual PG, canonical artifacts, gateway/Worker and source qualification boundaries."""

import json
from datetime import UTC, datetime
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


async def pipeline(engine, **seed_options):
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
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(model_output(wrapper))}}],
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
            store, execution, risk_sizing=SqlAnalysisRiskSizing(sessions)
        ),
    )
    command = AnalysisStart(
        request_id=uuid4(),
        portfolio_id=ids["portfolio"],
        instrument_id=ids["instrument"],
        model_profiles={role: profile.id for role in ANALYSIS_ROLES},
        evidence_ids=(ids["evidence"],),
        numeric_snapshot_id=ids["snapshot"],
        position_bucket="CORE",
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
