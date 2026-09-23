"""Explicit multi-provider research runtime routing.

Provider-specific HTTP and schema details stay in infrastructure.  This module only
resolves an owner-configured profile, reads its opaque credential reference, and
routes one explicitly selected request without fallback.
"""

from typing import Protocol
from uuid import UUID

from investment_os.application.provider_settings import DataProviderProfile, ProviderSettingsService
from investment_os.application.research import (
    ResearchArtifactDTO,
    ResearchProviderPort,
    ResearchRequest,
)
from investment_os.application.secrets import SecretStore


class ResearchRuntimeError(RuntimeError):
    """A configured research runtime cannot safely satisfy one explicit request."""


class ResearchProviderUnsupportedError(ResearchRuntimeError):
    """No infrastructure adapter is registered for the configured provider type."""


class ResearchProviderDisabledError(ResearchRuntimeError):
    """The owner has not enabled this provider profile for runtime use."""


class ResearchProviderCredentialError(ResearchRuntimeError):
    """The configured credential reference cannot be resolved safely."""


class ResearchProviderFactory(Protocol):
    def __call__(self, profile: DataProviderProfile, credential: str) -> ResearchProviderPort: ...


class DataProviderRuntimeRegistry:
    """Map a provider type to one infrastructure adapter factory.

    The registry intentionally has no priority or fallback semantics.  Each request
    names a profile, and failures remain attributable to that one profile.
    """

    def __init__(self, factories: dict[str, ResearchProviderFactory] | None = None) -> None:
        self._factories = dict(factories or {})

    def create(self, profile: DataProviderProfile, credential: str) -> ResearchProviderPort:
        factory = self._factories.get(profile.provider_type)
        if factory is None:
            raise ResearchProviderUnsupportedError("configured research provider is unsupported")
        return factory(profile, credential)

    @property
    def provider_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))


class ResearchProviderRuntime:
    """Resolve one enabled profile and fetch its untrusted normalized artifacts."""

    def __init__(
        self,
        *,
        provider_settings: ProviderSettingsService,
        secret_store: SecretStore,
        registry: DataProviderRuntimeRegistry,
    ) -> None:
        self._provider_settings = provider_settings
        self._secret_store = secret_store
        self._registry = registry

    async def fetch(
        self, *, profile_id: UUID, request: ResearchRequest
    ) -> list[ResearchArtifactDTO]:
        profile = await self._provider_settings.get_data_profile(profile_id)
        if profile is None:
            raise ResearchRuntimeError("configured research provider was not found")
        if not profile.enabled:
            raise ResearchProviderDisabledError("configured research provider is disabled")
        if profile.credential_ref is None:
            raise ResearchProviderCredentialError(
                "configured research provider credential is unavailable"
            )
        try:
            credential = await self._secret_store.get(profile.credential_ref)
        except RuntimeError as exc:
            raise ResearchProviderCredentialError(
                "configured research provider credential is unavailable"
            ) from exc
        if credential is None:
            raise ResearchProviderCredentialError(
                "configured research provider credential is unavailable"
            )
        provider = self._registry.create(profile, credential)
        return await provider.fetch_artifacts(request)
