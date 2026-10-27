"""Production composition root for the HTTP application."""

from datetime import UTC, datetime

from fastapi import FastAPI

from investment_os.application.calendar_product import CalendarProductService
from investment_os.application.instrument_catalog import InstrumentCatalogService
from investment_os.application.llm_budget import LLMBudgetService
from investment_os.application.market_data import MarketDataService
from investment_os.application.onboarding import OnboardingService
from investment_os.application.opportunities import OpportunityService
from investment_os.application.portfolio_book import PortfolioBookService
from investment_os.application.portfolio_valuation import PortfolioValuationService
from investment_os.application.provider_settings import ProviderSettingsService
from investment_os.application.research_runtime import (
    DataProviderRuntimeRegistry,
    ResearchProviderRuntime,
)
from investment_os.application.secrets import SecretStore, UnavailableSecretStore
from investment_os.infrastructure.bocha.adapter import (
    BochaWebSearchConnectionTester,
)
from investment_os.infrastructure.calendar_product import SqlCalendarProduct
from investment_os.infrastructure.catalog_portfolio import (
    SessionCatalogPort,
    SessionPortfolioBookPort,
)
from investment_os.infrastructure.database import create_database_engine, create_session_factory
from investment_os.infrastructure.evidence_ingestion import SqlAlchemyEvidenceIngestor
from investment_os.infrastructure.llm_budget import SqlAlchemyLLMBudgetStore
from investment_os.infrastructure.manual_market_data import SqlManualMarketData
from investment_os.infrastructure.onboarding import (
    SqlAlchemyOnboardingRuntime,
    SqlAlchemyOnboardingStore,
)
from investment_os.infrastructure.openai_compatible_llm import OpenAICompatibleLLMGateway
from investment_os.infrastructure.opportunities import LocalExplicitUniverse, SqlOpportunityStore
from investment_os.infrastructure.portfolio_valuation import SqlValuationInputs
from investment_os.infrastructure.provider_settings import SqlAlchemyProviderSettingsStore
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
    manual_market = SqlManualMarketData(session_factory)
    catalog = SessionCatalogPort(session_factory)
    market_data = MarketDataService(
        {"MANUAL_MARKET": manual_market},
        manual_market,
        InstrumentCatalogService(catalog),
        PortfolioBookService(SessionPortfolioBookPort(session_factory), catalog),
    )
    research_provider_runtime = ResearchProviderRuntime(
        provider_settings=provider_settings_service,
        secret_store=secret_store,
        registry=DataProviderRuntimeRegistry(
            {"BOCHA_WEB_SEARCH": data_connection_tester.provider_for}
        ),
    )
    funnel_store = SqlOpportunityStore(session_factory)
    opportunities = OpportunityService(
        LocalExplicitUniverse(InstrumentCatalogService(catalog)),
        funnel_store,
        market_data,
        funnel_store,
    )
    return create_app(
        opportunity_service=opportunities,
        calendar_product_service=CalendarProductService(SqlCalendarProduct(session_factory)),
        market_data_service=market_data,
        valuation_service=PortfolioValuationService(
            SqlValuationInputs(session_factory), market_data
        ),
        onboarding_service=onboarding_runtime.service,
        provider_settings_service=provider_settings_service,
        model_connection_tester=model_gateway,
        data_connection_tester=data_connection_tester,
        research_provider_runtime=research_provider_runtime,
        evidence_ingestor=SqlAlchemyEvidenceIngestor(
            session_factory,
            now=lambda: datetime.now(UTC),
        ),
        llm_budget_service=budget_service,
        onboarding_lifecycle=onboarding_runtime,
    )


app = create_production_app()
