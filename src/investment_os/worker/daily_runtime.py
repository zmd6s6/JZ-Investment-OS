"""Production daily runner composition; no test data or implicit research grants."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.analysis_configuration import AnalysisStartService
from investment_os.application.instrument_catalog import InstrumentCatalogService
from investment_os.application.llm_budget import LLMBudgetService
from investment_os.application.market_data import MarketDataService
from investment_os.application.portfolio_book import PortfolioBookService
from investment_os.application.portfolio_valuation import PortfolioValuationService
from investment_os.application.provider_settings import ProviderSettingsService
from investment_os.application.secrets import SecretStore, UnavailableSecretStore
from investment_os.infrastructure.analysis_runs import SqlAnalysisRuns
from investment_os.infrastructure.catalog_portfolio import (
    SessionCatalogPort,
    SessionPortfolioBookPort,
)
from investment_os.infrastructure.daily_runtime_local import SqlDailyLocalReader
from investment_os.infrastructure.daily_runtime_runner import DailyRuntimeRunner
from investment_os.infrastructure.llm_budget import SqlAlchemyLLMBudgetStore
from investment_os.infrastructure.manual_market_data import SqlManualMarketData
from investment_os.infrastructure.portfolio_valuation import SqlValuationInputs
from investment_os.infrastructure.provider_settings import SqlAlchemyProviderSettingsStore
from investment_os.infrastructure.secrets import EncryptedFileSecretStore
from investment_os.infrastructure.settings import Settings


def daily_worker(
    sessions: async_sessionmaker[AsyncSession], settings: Settings
) -> DailyRuntimeRunner:
    try:
        secrets: SecretStore = EncryptedFileSecretStore(
            settings.secret_store_path, settings.secret_store_key or ""
        )
    except RuntimeError:
        secrets = UnavailableSecretStore("daily worker secret store unavailable")
    providers = ProviderSettingsService(SqlAlchemyProviderSettingsStore(sessions), secrets)
    budget = LLMBudgetService(SqlAlchemyLLMBudgetStore(sessions))
    catalog_port = SessionCatalogPort(sessions)
    catalog = InstrumentCatalogService(catalog_port)
    quotes = SqlManualMarketData(sessions)
    market = MarketDataService(
        {"MANUAL_MARKET": quotes},
        quotes,
        catalog,
        PortfolioBookService(SessionPortfolioBookPort(sessions), catalog_port),
    )
    analyses = SqlAnalysisRuns(sessions)
    starter = AnalysisStartService(
        analyses,
        PortfolioValuationService(SqlValuationInputs(sessions), market),
        providers,
        budget,
        catalog,
    )
    return DailyRuntimeRunner(sessions, SqlDailyLocalReader(quotes), starter, analyses)
