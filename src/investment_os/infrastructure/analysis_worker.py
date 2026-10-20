"""Worker composition for explicitly queued investment research only."""

from investment_os.application.agent_runtime import AgentRuntime
from investment_os.application.analysis_jobs import AnalysisJobService
from investment_os.application.analysis_market import AnalysisMarketConfiguration
from investment_os.application.analysis_models import AnalysisModelConfiguration
from investment_os.application.analysis_orchestrator import default_registry
from investment_os.application.analysis_product import ProductAnalysisService
from investment_os.application.analysis_run import AnalysisRunService
from investment_os.application.committee_runtime import CommitteeRuntime
from investment_os.application.llm_budget import LLMBudgetService
from investment_os.application.market_data import InMemoryMarketDataAdapter
from investment_os.application.portfolio_book import PortfolioBookService
from investment_os.application.provider_settings import ProviderSettingsService
from investment_os.application.secrets import SecretStore, UnavailableSecretStore
from investment_os.infrastructure.analysis_inputs import SqlAlchemyAnalysisInputs
from investment_os.infrastructure.analysis_jobs import SqlAlchemyAnalysisJobs
from investment_os.infrastructure.analysis_market import PlannedMarketDataFactory
from investment_os.infrastructure.analysis_market_audit import SqlAnalysisMarketAudit
from investment_os.infrastructure.analysis_run_store import SessionAnalysisRunPort
from investment_os.infrastructure.catalog_portfolio import (
    SessionCatalogPort,
    SessionPortfolioBookPort,
)
from investment_os.infrastructure.database import create_database_engine, create_session_factory
from investment_os.infrastructure.llm_budget import SqlAlchemyLLMBudgetStore
from investment_os.infrastructure.openai_compatible_llm import OpenAICompatibleLLMGateway
from investment_os.infrastructure.provider_settings import SqlAlchemyProviderSettingsStore
from investment_os.infrastructure.secrets import EncryptedFileSecretStore
from investment_os.infrastructure.settings import Settings


class AnalysisWorker:
    def __init__(self, settings: Settings) -> None:
        self._engine = create_database_engine(settings.database_url)
        sessions = create_session_factory(self._engine)
        try:
            secrets: SecretStore = EncryptedFileSecretStore(
                settings.secret_store_path, settings.secret_store_key or ""
            )
        except RuntimeError as error:
            secrets = UnavailableSecretStore(str(error))
        profiles = ProviderSettingsService(SqlAlchemyProviderSettingsStore(sessions), secrets)
        self._gateway = OpenAICompatibleLLMGateway(
            provider_settings=profiles,
            secret_store=secrets,
            budget_service=LLMBudgetService(SqlAlchemyLLMBudgetStore(sessions)),
        )
        catalog = SessionCatalogPort(sessions)
        market_factory = PlannedMarketDataFactory(profiles, secrets)
        product = ProductAnalysisService(
            inputs=SqlAlchemyAnalysisInputs(sessions),
            portfolios=PortfolioBookService(SessionPortfolioBookPort(sessions), catalog),
            analysis_runs=AnalysisRunService(SessionAnalysisRunPort(sessions)),
            committee=CommitteeRuntime(
                agent_runtime=AgentRuntime(registry=default_registry(), gateway=self._gateway)
            ),
            market_data=InMemoryMarketDataAdapter(),
            catalog=catalog,
            model_configuration=AnalysisModelConfiguration(profiles),
            market_configuration=AnalysisMarketConfiguration(
                profiles, market_factory.supported_types
            ),
            market_factory=market_factory,
            market_audit=SqlAnalysisMarketAudit(sessions),
        )
        self.jobs = AnalysisJobService(SqlAlchemyAnalysisJobs(self._engine, sessions), product)

    async def run_once(self) -> bool:
        return await self.jobs.run_once()

    async def close(self) -> None:
        await self._gateway.close()
        await self._engine.dispose()
