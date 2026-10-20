"""Production composition root for the HTTP application."""

from datetime import UTC, datetime

from fastapi import FastAPI

from investment_os.application.analysis_jobs import AnalysisJobService
from investment_os.application.analysis_market import AnalysisMarketConfiguration
from investment_os.application.analysis_models import AnalysisModelConfiguration
from investment_os.application.llm_budget import LLMBudgetService
from investment_os.application.onboarding import OnboardingService
from investment_os.application.provider_settings import ProviderSettingsService
from investment_os.application.research_preview import ResearchPreviewService
from investment_os.application.research_runtime import (
    DataProviderRuntimeRegistry,
    ResearchProviderRuntime,
)
from investment_os.application.secrets import SecretStore, UnavailableSecretStore
from investment_os.infrastructure.analysis_inputs import SqlAlchemyAnalysisInputs
from investment_os.infrastructure.analysis_jobs import SqlAlchemyAnalysisJobs
from investment_os.infrastructure.analysis_market import PlannedMarketDataFactory
from investment_os.infrastructure.bocha.adapter import (
    BochaWebSearchConnectionTester,
)
from investment_os.infrastructure.database import create_database_engine, create_session_factory
from investment_os.infrastructure.evidence_ingestion import SqlAlchemyEvidenceIngestor
from investment_os.infrastructure.llm_budget import SqlAlchemyLLMBudgetStore
from investment_os.infrastructure.onboarding import (
    SqlAlchemyOnboardingRuntime,
    SqlAlchemyOnboardingStore,
)
from investment_os.infrastructure.openai_compatible_llm import OpenAICompatibleLLMGateway
from investment_os.infrastructure.provider_settings import SqlAlchemyProviderSettingsStore
from investment_os.infrastructure.research_preview import SqlAlchemyResearchPreviews
from investment_os.infrastructure.secrets import EncryptedFileSecretStore
from investment_os.infrastructure.settings import get_settings

from .app import create_app


def create_production_app() -> FastAPI:
    """Inject infrastructure adapters into application use cases for production."""

    settings = get_settings()
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    onboarding_runtime = SqlAlchemyOnboardingRuntime(
        engine,
        OnboardingService(SqlAlchemyOnboardingStore(session_factory)),
    )
    try:
        secret_store: SecretStore = EncryptedFileSecretStore(
            settings.secret_store_path, settings.secret_store_key or ""
        )
    except RuntimeError as exc:
        secret_store = UnavailableSecretStore(str(exc))
    provider_settings_service = ProviderSettingsService(
        SqlAlchemyProviderSettingsStore(session_factory),
        secret_store,
    )
    budget_service = LLMBudgetService(SqlAlchemyLLMBudgetStore(session_factory))
    model_gateway = OpenAICompatibleLLMGateway(
        provider_settings=provider_settings_service,
        secret_store=secret_store,
        budget_service=budget_service,
    )
    data_connection_tester = BochaWebSearchConnectionTester()
    from investment_os.infrastructure.market_data_tester import (
        CompositeDataProviderConnectionTester,
    )
    from investment_os.infrastructure.tushare.market_data import TushareConnectionTester

    composite_data_tester = CompositeDataProviderConnectionTester(
        bocha_tester=data_connection_tester,
        tushare_tester=TushareConnectionTester(),
    )
    research_provider_runtime = ResearchProviderRuntime(
        provider_settings=provider_settings_service,
        secret_store=secret_store,
        registry=DataProviderRuntimeRegistry(
            {"BOCHA_WEB_SEARCH": data_connection_tester.provider_for}
        ),
    )

    from investment_os.application.agent_runtime import AgentRuntime
    from investment_os.application.analysis_orchestrator import default_registry
    from investment_os.application.analysis_product import ProductAnalysisService
    from investment_os.application.analysis_run import AnalysisRunService
    from investment_os.application.committee_runtime import CommitteeRuntime
    from investment_os.application.instrument_catalog import InstrumentCatalogService
    from investment_os.application.market_data import (
        InMemoryMarketDataAdapter,
    )
    from investment_os.application.portfolio_book import PortfolioBookService
    from investment_os.infrastructure.analysis_run_store import SessionAnalysisRunPort
    from investment_os.infrastructure.catalog_portfolio import (
        SessionCatalogPort,
        SessionPortfolioBookPort,
    )

    catalog_adapter = SessionCatalogPort(session_factory)
    agent_runtime = AgentRuntime(registry=default_registry(), gateway=model_gateway)
    committee = CommitteeRuntime(agent_runtime=agent_runtime)
    portfolio_book = PortfolioBookService(
        SessionPortfolioBookPort(session_factory), catalog_adapter
    )
    analysis_runs = AnalysisRunService(SessionAnalysisRunPort(session_factory))

    market_factory = PlannedMarketDataFactory(provider_settings_service, secret_store)
    from investment_os.infrastructure.analysis_market_audit import SqlAnalysisMarketAudit

    analysis_product = ProductAnalysisService(
        inputs=SqlAlchemyAnalysisInputs(session_factory),
        portfolios=portfolio_book,
        analysis_runs=analysis_runs,
        committee=committee,
        market_data=InMemoryMarketDataAdapter(),
        catalog=catalog_adapter,
        model_configuration=AnalysisModelConfiguration(provider_settings_service),
        market_configuration=AnalysisMarketConfiguration(
            provider_settings_service, market_factory.supported_types
        ),
        market_factory=market_factory,
        market_audit=SqlAnalysisMarketAudit(session_factory),
    )

    return create_app(
        onboarding_service=onboarding_runtime.service,
        provider_settings_service=provider_settings_service,
        model_connection_tester=model_gateway,
        data_connection_tester=composite_data_tester,
        research_provider_runtime=research_provider_runtime,
        evidence_ingestor=SqlAlchemyEvidenceIngestor(
            session_factory,
            now=lambda: datetime.now(UTC),
        ),
        llm_budget_service=budget_service,
        onboarding_lifecycle=onboarding_runtime,
        portfolio_book_service=portfolio_book,
        instrument_catalog_service=InstrumentCatalogService(catalog_adapter),
        analysis_product_service=analysis_product,
        analysis_run_service=analysis_runs,
        analysis_job_service=AnalysisJobService(
            SqlAlchemyAnalysisJobs(engine, session_factory), analysis_product
        ),
        research_preview_service=ResearchPreviewService(
            SqlAlchemyResearchPreviews(session_factory),
            research_provider_runtime,
            now=lambda: datetime.now(UTC),
        ),
    )


app = create_production_app()
