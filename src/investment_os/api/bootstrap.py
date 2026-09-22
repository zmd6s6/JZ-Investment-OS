"""Production composition root for the HTTP application."""

from fastapi import FastAPI

from investment_os.application.llm_budget import LLMBudgetService
from investment_os.application.onboarding import OnboardingService
from investment_os.application.provider_settings import ProviderSettingsService
from investment_os.application.secrets import SecretStore, UnavailableSecretStore
from investment_os.infrastructure.database import create_database_engine, create_session_factory
from investment_os.infrastructure.llm_budget import SqlAlchemyLLMBudgetStore
from investment_os.infrastructure.onboarding import (
    SqlAlchemyOnboardingRuntime,
    SqlAlchemyOnboardingStore,
)
from investment_os.infrastructure.openai_compatible_llm import OpenAICompatibleLLMGateway
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
    return create_app(
        onboarding_service=onboarding_runtime.service,
        provider_settings_service=provider_settings_service,
        model_connection_tester=model_gateway,
        llm_budget_service=budget_service,
        onboarding_lifecycle=onboarding_runtime,
    )


app = create_production_app()
