from uuid import UUID

from httpx import ASGITransport, AsyncClient

from investment_os.api.app import create_app
from investment_os.application.provider_settings import (
    DataProviderProfile,
    ModelProviderProfile,
    ProviderSettingsService,
    ProviderTestResult,
    RoleModelAssignment,
    SystemSettings,
)
from investment_os.application.secrets import UnavailableSecretStore


class MemorySecretStore:
    def __init__(self) -> None:
        self.values: dict[UUID, str] = {}

    async def put(self, credential_ref: UUID, value: str) -> None:
        self.values[credential_ref] = value

    async def get(self, credential_ref: UUID) -> str | None:
        return self.values.get(credential_ref)

    async def delete(self, credential_ref: UUID) -> None:
        self.values.pop(credential_ref, None)


class MemoryProviderSettingsPort:
    def __init__(self) -> None:
        self.settings = SystemSettings(market_timezone="Asia/Shanghai", market_scopes=())
        self.models: dict[UUID, ModelProviderProfile] = {}
        self.data: dict[UUID, DataProviderProfile] = {}
        self.assignments: dict[str, RoleModelAssignment] = {}
        self.tests: list[tuple[UUID, str, ProviderTestResult]] = []

    async def get_system_settings(self) -> SystemSettings:
        return self.settings

    async def save_system_settings(self, settings: SystemSettings) -> SystemSettings:
        self.settings = settings
        return settings

    async def list_model_profiles(self) -> list[ModelProviderProfile]:
        return list(self.models.values())

    async def get_model_profile(self, profile_id: UUID) -> ModelProviderProfile | None:
        return self.models.get(profile_id)

    async def save_model_profile(self, profile: ModelProviderProfile) -> ModelProviderProfile:
        self.models[profile.id] = profile
        return profile

    async def delete_model_profile(self, profile_id: UUID) -> bool:
        return self.models.pop(profile_id, None) is not None

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
        return list(self.assignments.values())

    async def save_role_assignment(self, assignment: RoleModelAssignment) -> RoleModelAssignment:
        self.assignments[assignment.role] = assignment
        return assignment

    async def record_provider_test(
        self, *, profile_id: UUID, provider_kind: str, result: ProviderTestResult
    ) -> None:
        self.tests.append((profile_id, provider_kind, result))


def _model_request(credential: str | None = "synthetic-credential") -> dict[str, object]:
    request: dict[str, object] = {
        "name": "primary-model",
        "provider_type": "OPENAI_COMPATIBLE",
        "base_url": "https://models.example.invalid/v1",
        "model_name": "synthetic-model",
        "timeout_seconds": 30,
        "max_tokens": 1024,
        "enabled": True,
    }
    if credential is not None:
        request["credential"] = credential
    return request


async def test_provider_settings_api_hides_credentials_and_records_no_network_test() -> None:
    port = MemoryProviderSettingsPort()
    secret_store = MemorySecretStore()
    app = create_app(
        provider_settings_service=ProviderSettingsService(port, secret_store)  # type: ignore[arg-type]
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        updated_settings = await client.put(
            "/api/v1/settings/system",
            json={"market_timezone": "Asia/Shanghai", "market_scopes": ["CN", "HK"]},
        )
        created_model = await client.post("/api/v1/settings/model-providers", json=_model_request())
        model_id = created_model.json()["id"]
        tested_model = await client.post(f"/api/v1/settings/model-providers/{model_id}/test")
        role_assignment = await client.put(
            "/api/v1/settings/role-model-assignments/DEFAULT",
            json={"model_provider_profile_id": model_id},
        )
        created_data = await client.post(
            "/api/v1/settings/data-providers",
            json={
                "name": "research-feed",
                "provider_type": "DSA_ADAPTER",
                "base_url": "https://data.example.invalid",
                "timeout_seconds": 30,
                "enabled": False,
            },
        )
        data_id = created_data.json()["id"]
        tested_data = await client.post(f"/api/v1/settings/data-providers/{data_id}/test")
        capabilities = await client.get("/api/v1/product-capabilities")

    assert updated_settings.json() == {
        "schema_version": "1.0",
        "market_timezone": "Asia/Shanghai",
        "market_scopes": ["CN", "HK"],
        "auto_trade": False,
    }
    assert created_model.status_code == 201
    assert created_model.json()["credential_configured"] is True
    assert set(created_model.json()) == {
        "schema_version",
        "id",
        "name",
        "provider_type",
        "base_url",
        "model_name",
        "timeout_seconds",
        "max_tokens",
        "enabled",
        "credential_configured",
    }
    assert "synthetic-credential" not in str(created_model.json())
    assert tested_model.json()["status"] == "CONFIGURATION_VALID"
    assert role_assignment.json()["role"] == "DEFAULT"
    assert created_data.status_code == 201
    assert tested_data.json()["status"] == "CREDENTIAL_MISSING"
    assert port.tests[0][1] == "MODEL"
    assert port.tests[1][1] == "DATA"
    assert next(item for item in capabilities.json() if item["key"] == "providers")["status"] == (
        "CONFIGURATION_REQUIRED"
    )


async def test_provider_settings_api_fails_closed_when_secret_store_is_unavailable() -> None:
    app = create_app(
        provider_settings_service=ProviderSettingsService(
            MemoryProviderSettingsPort(),  # type: ignore[arg-type]
            UnavailableSecretStore("secret store key is not configured"),
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/settings/model-providers", json=_model_request())

    assert response.status_code == 503
    assert response.json() == {"detail": "secret_store_unavailable"}


async def test_role_assignment_rejects_disabled_model_profile() -> None:
    port = MemoryProviderSettingsPort()
    service = ProviderSettingsService(port, MemorySecretStore())  # type: ignore[arg-type]
    profile = await service.save_model_profile(
        profile_id=None,
        name="disabled-model",
        provider_type="OPENAI_COMPATIBLE",
        base_url="https://models.example.invalid",
        model_name="synthetic-model",
        timeout_seconds=30,
        max_tokens=1024,
        enabled=False,
        credential=None,
    )
    app = create_app(provider_settings_service=service)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            "/api/v1/settings/role-model-assignments/RISK",
            json={"model_provider_profile_id": str(profile.id)},
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "a disabled model provider cannot be assigned"}


async def test_role_resolution_uses_enabled_default_when_role_has_no_assignment() -> None:
    port = MemoryProviderSettingsPort()
    service = ProviderSettingsService(port, MemorySecretStore())  # type: ignore[arg-type]
    profile = await service.save_model_profile(
        profile_id=None,
        name="default-model",
        provider_type="OPENAI_COMPATIBLE",
        base_url="https://models.example.invalid",
        model_name="synthetic-model",
        timeout_seconds=30,
        max_tokens=1024,
        enabled=True,
        credential=None,
    )
    await service.save_role_assignment(
        role="DEFAULT",
        model_provider_profile_id=profile.id,
    )

    assert await service.model_for_role("RISK") == profile
