"""Production-only composition for queued analysis; no synthetic or fallback gateway."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.investment_analysis import InvestmentAnalysisOrchestrator
from investment_os.application.llm_budget import LLMBudgetService
from investment_os.application.provider_settings import ProviderSettingsService
from investment_os.application.research_runtime import (
    DataProviderRuntimeRegistry,
    ResearchProviderRuntime,
)
from investment_os.application.secrets import SecretStore, UnavailableSecretStore
from investment_os.infrastructure.analysis_execution import SqlAnalysisExecution
from investment_os.infrastructure.analysis_inputs import (
    AnalysisGatewayFactory,
    SqlAnalysisInputPreparer,
)
from investment_os.infrastructure.analysis_risk_sizing import SqlAnalysisRiskSizing
from investment_os.infrastructure.analysis_runs import SqlAnalysisRuns
from investment_os.infrastructure.bocha.adapter import BochaWebSearchConnectionTester
from investment_os.infrastructure.evidence_ingestion import SqlAlchemyEvidenceIngestor
from investment_os.infrastructure.llm_budget import SqlAlchemyLLMBudgetStore
from investment_os.infrastructure.provider_settings import SqlAlchemyProviderSettingsStore
from investment_os.infrastructure.secrets import EncryptedFileSecretStore
from investment_os.infrastructure.settings import Settings
from investment_os.worker.analysis_runner import AnalysisWorkerRunner


def analysis_worker(
    sessions: async_sessionmaker[AsyncSession], settings: Settings
) -> tuple[AnalysisWorkerRunner, SqlAnalysisExecution]:
    try:
        secrets: SecretStore = EncryptedFileSecretStore(
            settings.secret_store_path, settings.secret_store_key or ""
        )
    except RuntimeError:
        secrets = UnavailableSecretStore("analysis worker secret store is unavailable")
    providers = ProviderSettingsService(SqlAlchemyProviderSettingsStore(sessions), secrets)
    budget = LLMBudgetService(SqlAlchemyLLMBudgetStore(sessions))
    store = SqlAnalysisRuns(sessions)
    research = ResearchProviderRuntime(
        provider_settings=providers,
        secret_store=secrets,
        registry=DataProviderRuntimeRegistry(
            {"BOCHA_WEB_SEARCH": BochaWebSearchConnectionTester().provider_for}
        ),
    )
    execution = SqlAnalysisExecution(
        sessions,
        SqlAnalysisInputPreparer(
            sessions,
            store,
            providers,
            research,
            SqlAlchemyEvidenceIngestor(sessions, now=lambda: datetime.now(UTC)),
        ),
        AnalysisGatewayFactory(providers, secrets, budget, store),
    )
    return AnalysisWorkerRunner(
        store,
        InvestmentAnalysisOrchestrator(
            store, execution, risk_sizing=SqlAnalysisRiskSizing(sessions)
        ),
    ), execution
