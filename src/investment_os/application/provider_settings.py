"""Application use cases for non-sensitive provider configuration."""

from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlparse
from uuid import UUID, uuid4

from investment_os.application.secrets import SecretStore
from investment_os.domain.agent import AgentRole

ProviderTestStatus = Literal[
    "CONFIGURATION_VALID",
    "CREDENTIAL_MISSING",
    "SECRET_STORE_UNAVAILABLE",
    "CONNECTION_SUCCEEDED",
    "CONNECTION_FAILED",
    "UNSUPPORTED_PROVIDER",
]


@dataclass(frozen=True, slots=True)
class SystemSettings:
    """Owner-selected product defaults; V1 trading automation is always disabled."""

    market_timezone: str
    market_scopes: tuple[str, ...]
    auto_trade: Literal[False] = False


@dataclass(frozen=True, slots=True)
class ModelProviderProfile:
    id: UUID
    name: str
    provider_type: str
    base_url: str
    model_name: str
    credential_ref: UUID | None
    timeout_seconds: int
    max_tokens: int
    enabled: bool


@dataclass(frozen=True, slots=True)
class DataProviderProfile:
    id: UUID
    name: str
    provider_type: str
    base_url: str
    credential_ref: UUID | None
    timeout_seconds: int
    enabled: bool


@dataclass(frozen=True, slots=True)
class RoleModelAssignment:
    role: str
    model_provider_profile_id: UUID


@dataclass(frozen=True, slots=True)
class ProviderTestResult:
    status: ProviderTestStatus
    detail: str
    latency_ms: int | None = None


class ModelProviderConnectionTester(Protocol):
    """Perform an explicit, credentialed model connection check without persisting a secret."""

    async def test_connection(
        self, *, profile: ModelProviderProfile, credential: str
    ) -> ProviderTestResult: ...


class ProviderSettingsPort(Protocol):
    """Persistence boundary for P2 settings and provider metadata."""

    async def get_system_settings(self) -> SystemSettings: ...

    async def save_system_settings(self, settings: SystemSettings) -> SystemSettings: ...

    async def list_model_profiles(self) -> list[ModelProviderProfile]: ...

    async def get_model_profile(self, profile_id: UUID) -> ModelProviderProfile | None: ...

    async def save_model_profile(self, profile: ModelProviderProfile) -> ModelProviderProfile: ...

    async def delete_model_profile(self, profile_id: UUID) -> bool: ...

    async def list_data_profiles(self) -> list[DataProviderProfile]: ...

    async def get_data_profile(self, profile_id: UUID) -> DataProviderProfile | None: ...

    async def save_data_profile(self, profile: DataProviderProfile) -> DataProviderProfile: ...

    async def delete_data_profile(self, profile_id: UUID) -> bool: ...

    async def list_role_assignments(self) -> list[RoleModelAssignment]: ...

    async def save_role_assignment(
        self, assignment: RoleModelAssignment
    ) -> RoleModelAssignment: ...

    async def record_provider_test(
        self,
        *,
        profile_id: UUID,
        provider_kind: Literal["MODEL", "DATA"],
        result: ProviderTestResult,
    ) -> None: ...


def _non_empty(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be blank")
    return normalized


def _valid_url(value: str) -> str:
    normalized = _non_empty(value, "base_url")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must be an absolute HTTP(S) URL")
    return normalized.rstrip("/")


class ProviderSettingsService:
    """Coordinate secret references with the persistence port without exposing secret values."""

    def __init__(self, settings_port: ProviderSettingsPort, secret_store: SecretStore) -> None:
        self._settings_port = settings_port
        self._secret_store = secret_store

    async def system_settings(self) -> SystemSettings:
        return await self._settings_port.get_system_settings()

    async def save_system_settings(
        self, *, market_timezone: str, market_scopes: tuple[str, ...]
    ) -> SystemSettings:
        normalized_scopes = tuple(_non_empty(scope, "market_scope") for scope in market_scopes)
        if len(set(normalized_scopes)) != len(normalized_scopes):
            raise ValueError("market_scopes must not repeat a value")
        return await self._settings_port.save_system_settings(
            SystemSettings(
                market_timezone=_non_empty(market_timezone, "market_timezone"),
                market_scopes=normalized_scopes,
            )
        )

    async def list_model_profiles(self) -> list[ModelProviderProfile]:
        return await self._settings_port.list_model_profiles()

    async def get_model_profile(self, profile_id: UUID) -> ModelProviderProfile | None:
        return await self._settings_port.get_model_profile(profile_id)

    async def save_model_profile(
        self,
        *,
        profile_id: UUID | None,
        name: str,
        provider_type: str,
        base_url: str,
        model_name: str,
        timeout_seconds: int,
        max_tokens: int,
        enabled: bool,
        credential: str | None,
    ) -> ModelProviderProfile:
        if timeout_seconds < 1 or max_tokens < 1:
            raise ValueError("timeout_seconds and max_tokens must be positive")
        existing = (
            await self._settings_port.get_model_profile(profile_id)
            if profile_id is not None
            else None
        )
        if profile_id is not None and existing is None:
            raise LookupError("model_provider_not_found")
        credential_ref = await self._replace_credential(
            current_ref=existing.credential_ref if existing else None,
            credential=credential,
        )
        return await self._settings_port.save_model_profile(
            ModelProviderProfile(
                id=profile_id or uuid4(),
                name=_non_empty(name, "name"),
                provider_type=_non_empty(provider_type, "provider_type"),
                base_url=_valid_url(base_url),
                model_name=_non_empty(model_name, "model_name"),
                credential_ref=credential_ref,
                timeout_seconds=timeout_seconds,
                max_tokens=max_tokens,
                enabled=enabled,
            )
        )

    async def delete_model_profile(self, profile_id: UUID) -> bool:
        return await self._settings_port.delete_model_profile(profile_id)

    async def list_data_profiles(self) -> list[DataProviderProfile]:
        return await self._settings_port.list_data_profiles()

    async def get_data_profile(self, profile_id: UUID) -> DataProviderProfile | None:
        return await self._settings_port.get_data_profile(profile_id)

    async def save_data_profile(
        self,
        *,
        profile_id: UUID | None,
        name: str,
        provider_type: str,
        base_url: str,
        timeout_seconds: int,
        enabled: bool,
        credential: str | None,
    ) -> DataProviderProfile:
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        existing = (
            await self._settings_port.get_data_profile(profile_id)
            if profile_id is not None
            else None
        )
        if profile_id is not None and existing is None:
            raise LookupError("data_provider_not_found")
        credential_ref = await self._replace_credential(
            current_ref=existing.credential_ref if existing else None,
            credential=credential,
        )
        return await self._settings_port.save_data_profile(
            DataProviderProfile(
                id=profile_id or uuid4(),
                name=_non_empty(name, "name"),
                provider_type=_non_empty(provider_type, "provider_type"),
                base_url=_valid_url(base_url),
                credential_ref=credential_ref,
                timeout_seconds=timeout_seconds,
                enabled=enabled,
            )
        )

    async def delete_data_profile(self, profile_id: UUID) -> bool:
        return await self._settings_port.delete_data_profile(profile_id)

    async def list_role_assignments(self) -> list[RoleModelAssignment]:
        return await self._settings_port.list_role_assignments()

    async def save_role_assignment(
        self, *, role: str, model_provider_profile_id: UUID
    ) -> RoleModelAssignment:
        accepted_roles = {"DEFAULT", *(member.value for member in AgentRole)}
        if role not in accepted_roles:
            raise ValueError("role is not supported")
        profile = await self._settings_port.get_model_profile(model_provider_profile_id)
        if profile is None:
            raise LookupError("model_provider_not_found")
        if not profile.enabled:
            raise ValueError("a disabled model provider cannot be assigned")
        return await self._settings_port.save_role_assignment(
            RoleModelAssignment(role=role, model_provider_profile_id=model_provider_profile_id)
        )

    async def model_for_role(self, role: str) -> ModelProviderProfile:
        """Resolve an explicit role assignment, then DEFAULT, while failing closed."""

        assignments = {
            assignment.role: assignment
            for assignment in await self._settings_port.list_role_assignments()
        }
        assignment = assignments.get(role) or assignments.get("DEFAULT")
        if assignment is None:
            raise LookupError("model_assignment_not_found")
        profile = await self._settings_port.get_model_profile(assignment.model_provider_profile_id)
        if profile is None or not profile.enabled:
            raise LookupError("assigned_model_provider_not_available")
        return profile

    async def test_model_profile(
        self,
        profile_id: UUID,
        *,
        connection_tester: ModelProviderConnectionTester | None = None,
    ) -> ProviderTestResult:
        profile = await self._settings_port.get_model_profile(profile_id)
        if profile is None:
            raise LookupError("model_provider_not_found")
        if connection_tester is None:
            result = await self._configuration_test(profile.credential_ref)
        else:
            result = await self._connection_test(
                profile=profile,
                connection_tester=connection_tester,
            )
        await self._settings_port.record_provider_test(
            profile_id=profile_id, provider_kind="MODEL", result=result
        )
        return result

    async def _connection_test(
        self,
        *,
        profile: ModelProviderProfile,
        connection_tester: ModelProviderConnectionTester,
    ) -> ProviderTestResult:
        if profile.credential_ref is None:
            return ProviderTestResult(
                status="CREDENTIAL_MISSING",
                detail="未配置凭据。未发起模型网络请求。",
            )
        try:
            credential = await self._secret_store.get(profile.credential_ref)
        except RuntimeError:
            return ProviderTestResult(
                status="SECRET_STORE_UNAVAILABLE",
                detail="加密凭据存储不可用。未发起模型网络请求。",
            )
        if credential is None:
            return ProviderTestResult(
                status="CREDENTIAL_MISSING",
                detail="凭据引用不存在。未发起模型网络请求。",
            )
        return await connection_tester.test_connection(profile=profile, credential=credential)

    async def test_data_profile(self, profile_id: UUID) -> ProviderTestResult:
        profile = await self._settings_port.get_data_profile(profile_id)
        if profile is None:
            raise LookupError("data_provider_not_found")
        result = await self._configuration_test(profile.credential_ref)
        await self._settings_port.record_provider_test(
            profile_id=profile_id, provider_kind="DATA", result=result
        )
        return result

    async def _replace_credential(
        self, *, current_ref: UUID | None, credential: str | None
    ) -> UUID | None:
        if credential is None:
            return current_ref
        normalized = _non_empty(credential, "credential")
        credential_ref = current_ref or uuid4()
        await self._secret_store.put(credential_ref, normalized)
        return credential_ref

    async def _configuration_test(self, credential_ref: UUID | None) -> ProviderTestResult:
        if credential_ref is None:
            return ProviderTestResult(
                status="CREDENTIAL_MISSING",
                detail="未配置凭据 P2 不会发起任何网络请求",
            )
        try:
            credential = await self._secret_store.get(credential_ref)
        except RuntimeError:
            return ProviderTestResult(
                status="SECRET_STORE_UNAVAILABLE",
                detail="加密凭据存储不可用 未发起网络请求",
            )
        if credential is None:
            return ProviderTestResult(
                status="CREDENTIAL_MISSING",
                detail="凭据引用不存在 未发起网络请求",
            )
        return ProviderTestResult(
            status="CONFIGURATION_VALID",
            detail="配置与加密凭据均可读取 P2 未发起网络请求",
        )
