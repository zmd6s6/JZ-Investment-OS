"""Production composition root for the HTTP application."""

from fastapi import FastAPI

from investment_os.application.onboarding import OnboardingService
from investment_os.infrastructure.database import create_database_engine, create_session_factory
from investment_os.infrastructure.onboarding import (
    SqlAlchemyOnboardingRuntime,
    SqlAlchemyOnboardingStore,
)
from investment_os.infrastructure.settings import get_settings

from .app import create_app


def create_production_app() -> FastAPI:
    """Inject infrastructure adapters into application use cases for production."""

    settings = get_settings()
    engine = create_database_engine(settings.database_url)
    onboarding_runtime = SqlAlchemyOnboardingRuntime(
        engine,
        OnboardingService(SqlAlchemyOnboardingStore(create_session_factory(engine))),
    )
    return create_app(
        onboarding_service=onboarding_runtime.service,
        onboarding_lifecycle=onboarding_runtime,
    )


app = create_production_app()
