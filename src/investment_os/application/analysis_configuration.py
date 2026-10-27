"""Prepare explicit, version-pinned run choices without changing global role assignments."""

from dataclasses import asdict
from datetime import UTC, datetime
from urllib.parse import urlparse

from investment_os.application.analysis_runs import (
    ANALYSIS_ROLES,
    AnalysisQueuedInput,
    AnalysisRunView,
    AnalysisStart,
    AnalysisStorePort,
    SelectedData,
    SelectedModel,
)
from investment_os.application.instrument_catalog import InstrumentCatalogService
from investment_os.application.llm_budget import LLMBudgetService
from investment_os.application.portfolio_valuation import PortfolioValuationService, fingerprint
from investment_os.application.provider_settings import (
    DataProviderProfile,
    ModelProviderProfile,
    ProviderSettingsService,
)


def profile_hash(profile: ModelProviderProfile | DataProviderProfile) -> str:
    import json

    return fingerprint(json.loads(json.dumps(asdict(profile), default=str, sort_keys=True)))


def budget_hash(policy: object) -> str:
    import json
    from dataclasses import is_dataclass

    if not is_dataclass(policy) or isinstance(policy, type):
        raise ValueError("ANALYSIS_BUDGET_UNAVAILABLE")
    return fingerprint(json.loads(json.dumps(asdict(policy), default=str, sort_keys=True)))


def require_safe_profile_url(url: str) -> None:
    endpoint = urlparse(url)
    if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
        raise ValueError("ANALYSIS_PROVIDER_URL_CONTAINS_CREDENTIALS_OR_QUERY")


class AnalysisStartService:
    def __init__(
        self,
        store: AnalysisStorePort,
        valuation: PortfolioValuationService,
        providers: ProviderSettingsService,
        budget: LLMBudgetService,
        catalog: InstrumentCatalogService,
    ):
        self._store = store
        self._valuation = valuation
        self._providers = providers
        self._budget = budget
        self._catalog = catalog

    async def start(self, command: AnalysisStart) -> AnalysisRunView:
        existing = await self._store.find_request(command.request_id)
        if existing:
            if existing.request_hash != fingerprint(command.model_dump(mode="json")):
                raise ValueError("ANALYSIS_REQUEST_CONFLICT")
            return existing
        await self._catalog.get(command.instrument_id)
        valuation = await self._valuation.get_context(
            command.portfolio_id,
            source=command.market_source,
            source_name=command.market_source_name.strip(),
        )
        models = {}
        cache = {}
        for role in ANALYSIS_ROLES:
            identifier = command.model_profiles[role]
            if identifier not in cache:
                cache[identifier] = await self._providers.get_model_profile(identifier)
            model = cache[identifier]
            if (
                model is None
                or not model.enabled
                or model.credential_ref is None
                or model.provider_type != "OPENAI_COMPATIBLE"
            ):
                raise ValueError("ANALYSIS_MODEL_PROFILE_UNAVAILABLE")
            require_safe_profile_url(model.base_url)
            models[role] = SelectedModel(
                profile_id=model.id,
                name=model.name,
                model_name=model.model_name,
                config_hash=profile_hash(model),
                timeout_seconds=model.timeout_seconds,
                max_tokens=model.max_tokens,
            )
        data = []
        for identifier in command.data_profile_ids:
            profile = await self._providers.get_data_profile(identifier)
            if profile is None or not profile.enabled or profile.credential_ref is None:
                raise ValueError("ANALYSIS_DATA_PROFILE_UNAVAILABLE")
            require_safe_profile_url(profile.base_url)
            data.append(
                SelectedData(
                    profile_id=profile.id,
                    name=profile.name,
                    provider_type=profile.provider_type,
                    config_hash=profile_hash(profile),
                )
            )
        policy = await self._budget.policy()
        if policy is None:
            raise ValueError("ANALYSIS_BUDGET_UNAVAILABLE")
        return await self._store.enqueue(
            AnalysisQueuedInput(
                command=command,
                queued_at=datetime.now(UTC),
                valuation=valuation,
                models=models,
                data_profiles=tuple(data),
                budget_hash=budget_hash(policy),
            )
        )
