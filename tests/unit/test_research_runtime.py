from datetime import UTC, datetime
from uuid import UUID

import pytest

from investment_os.application.provider_settings import (
    DataProviderProfile,
    ModelProviderProfile,
    ProviderSettingsService,
    ProviderTestResult,
    RoleModelAssignment,
    SystemSettings,
)
from investment_os.application.research import ResearchArtifactDTO, ResearchRequest
from investment_os.application.research_runtime import (
    DataProviderRuntimeRegistry,
    ResearchProviderDisabledError,
    ResearchProviderRuntime,
    ResearchProviderUnsupportedError,
)
from investment_os.domain.values import UtcTimestamp

NOW = datetime(2026, 9, 22, tzinfo=UTC)


class MemorySecretStore:
    def __init__(self) -> None:
        self.values: dict[UUID, str] = {}

    async def put(self, credential_ref: UUID, value: str) -> None:
        self.values[credential_ref] = value

    async def get(self, credential_ref: UUID) -> str | None:
        return self.values.get(credential_ref)

    async def delete(self, credential_ref: UUID) -> None:
        self.values.pop(credential_ref, None)


class SettingsPort:
    def __init__(self) -> None:
        self.data: dict[UUID, DataProviderProfile] = {}

    async def get_system_settings(self) -> SystemSettings:
        return SystemSettings("Asia/Shanghai", ())

    async def save_system_settings(self, settings: SystemSettings) -> SystemSettings:
        return settings

    async def list_model_profiles(self) -> list[ModelProviderProfile]:
        return []

    async def get_model_profile(self, _: UUID) -> ModelProviderProfile | None:
        return None

    async def save_model_profile(self, profile: ModelProviderProfile) -> ModelProviderProfile:
        return profile

    async def delete_model_profile(self, _: UUID) -> bool:
        return False

    async def list_data_profiles(self) -> list[DataProviderProfile]:
        return list(self.data.values())

    async def get_data_profile(self, profile_id: UUID) -> DataProviderProfile | None:
        return self.data.get(profile_id)

    async def save_data_profile(self, profile: DataProviderProfile) -> DataProviderProfile:
        self.data[profile.id] = profile
        return profile

    async def delete_data_profile(self, profile_id: UUID) -> bool:
        return self.data.pop(profile_id, None) is not None

    async def list_role_assignments(self) -> list[RoleModelAssignment]:
        return []

    async def save_role_assignment(self, assignment: RoleModelAssignment) -> RoleModelAssignment:
        return assignment

    async def delete_role_assignment(self, _: str) -> bool:
        return False

    async def record_provider_test(
        self, *, profile_id: UUID, provider_kind: str, result: ProviderTestResult
    ) -> None:
        del profile_id, provider_kind, result


class StaticProvider:
    async def fetch_artifacts(self, request: ResearchRequest) -> list[ResearchArtifactDTO]:
        del request
        return []


async def _runtime(
    *, enabled: bool, provider_type: str = "SYNTHETIC"
) -> tuple[ResearchProviderRuntime, UUID]:
    port = SettingsPort()
    secrets = MemorySecretStore()
    service = ProviderSettingsService(port, secrets)  # type: ignore[arg-type]
    profile = await service.save_data_profile(
        profile_id=None,
        name="synthetic",
        provider_type=provider_type,
        base_url="https://provider.example.test",
        timeout_seconds=15,
        enabled=enabled,
        credential="synthetic-credential",
    )
    return (
        ResearchProviderRuntime(
            provider_settings=service,
            secret_store=secrets,
            registry=DataProviderRuntimeRegistry({"SYNTHETIC": lambda _, __: StaticProvider()}),
        ),
        profile.id,
    )


@pytest.mark.asyncio
async def test_runtime_routes_only_the_explicit_enabled_profile() -> None:
    runtime, profile_id = await _runtime(enabled=True)

    artifacts = await runtime.fetch(
        profile_id=profile_id,
        request=ResearchRequest((), UtcTimestamp(NOW), query="synthetic query"),
    )

    assert artifacts == []


@pytest.mark.asyncio
async def test_runtime_rejects_disabled_profile_before_creating_provider() -> None:
    runtime, profile_id = await _runtime(enabled=False)

    with pytest.raises(ResearchProviderDisabledError, match="disabled"):
        await runtime.fetch(
            profile_id=profile_id,
            request=ResearchRequest((), UtcTimestamp(NOW), query="synthetic query"),
        )


@pytest.mark.asyncio
async def test_runtime_rejects_unknown_provider_type_without_fallback() -> None:
    runtime, profile_id = await _runtime(enabled=True, provider_type="UNKNOWN")

    with pytest.raises(ResearchProviderUnsupportedError, match="unsupported"):
        await runtime.fetch(
            profile_id=profile_id,
            request=ResearchRequest((), UtcTimestamp(NOW), query="synthetic query"),
        )
