"""Secret-free, immutable model choices for a single explicitly submitted analysis."""

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.provider_settings import (
    ModelProviderProfile,
    ProviderSettingsService,
)
from investment_os.domain.agent import AgentRole

ANALYSIS_ROLES = (
    AgentRole.MACRO,
    AgentRole.INDUSTRY,
    AgentRole.FUNDAMENTAL,
    AgentRole.MARKET_QUANT,
    AgentRole.EVENT,
    AgentRole.DEVILS_ADVOCATE,
    AgentRole.PORTFOLIO,
    AgentRole.RISK,
)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


class FrozenModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile_id: UUID
    name: str
    provider_type: str
    model_name: str
    timeout_seconds: int
    max_tokens: int
    pricing_version: str | None
    pricing_currency: str | None
    input_token_price: Decimal | None
    output_token_price: Decimal | None
    pricing_effective_at: datetime | None
    configuration_hash: str

    @classmethod
    def capture(cls, profile: ModelProviderProfile) -> "FrozenModelProfile":
        # Credentials/references never enter the queue, API preview or report.
        # Hash the endpoint, rather than copying potential private URL components.
        values = asdict(profile)
        for key in ("credential_ref", "enabled"):
            values.pop(key)
        fingerprint = digest(values)
        values.pop("base_url")
        values["profile_id"] = values.pop("id")
        return cls(**values, configuration_hash=fingerprint)


class FrozenRoleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    role: AgentRole
    profile: FrozenModelProfile


class AnalysisModelPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0"] = "1.0"
    mode: Literal["ROLE_MAPPING", "SINGLE_PROFILE"]
    selected_profile_id: UUID | None = None
    bindings: tuple[FrozenRoleModel, ...]

    @model_validator(mode="after")
    def complete_team(self) -> "AnalysisModelPlan":
        if len(self.bindings) != len(ANALYSIS_ROLES) or {b.role for b in self.bindings} != set(
            ANALYSIS_ROLES
        ):
            raise ValueError("analysis model plan requires each analysis role exactly once")
        if self.mode == "SINGLE_PROFILE":
            if self.selected_profile_id is None or any(
                b.profile.profile_id != self.selected_profile_id for b in self.bindings
            ):
                raise ValueError("single profile plan must match its selected profile")
        elif self.selected_profile_id is not None:
            raise ValueError("role mapping plan cannot select a single profile")
        return self


class AnalysisModelOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0"] = "1.0"
    configuration_hash: str
    profiles: tuple[FrozenModelProfile, ...]
    default_bindings: tuple[FrozenRoleModel, ...]
    missing_roles: tuple[AgentRole, ...]


class AnalysisModelConfiguration:
    def __init__(self, settings: ProviderSettingsService) -> None:
        self._settings = settings

    async def options(self) -> AnalysisModelOptions:
        profiles = {
            p.id: FrozenModelProfile.capture(p)
            for p in await self._settings.list_model_profiles()
            if p.enabled and p.credential_ref is not None and p.provider_type == "OPENAI_COMPATIBLE"
        }
        assignments = {
            a.role: a.model_provider_profile_id
            for a in await self._settings.list_role_assignments()
        }
        bindings, missing = [], []
        for role in ANALYSIS_ROLES:
            selected = assignments.get(role.value, assignments.get("DEFAULT"))
            if selected not in profiles:
                missing.append(role)
            else:
                bindings.append(FrozenRoleModel(role=role, profile=profiles[selected]))
        ordered = tuple(profiles[i] for i in sorted(profiles, key=str))
        content = {
            "profiles": [p.model_dump(mode="json") for p in ordered],
            "bindings": [b.model_dump(mode="json") for b in bindings],
            "missing": missing,
        }
        return AnalysisModelOptions(
            configuration_hash=digest(content),
            profiles=ordered,
            default_bindings=tuple(bindings),
            missing_roles=tuple(missing),
        )

    async def freeze(self, profile_id: UUID | None, expected_hash: str | None) -> AnalysisModelPlan:
        options = await self.options()
        if expected_hash is not None and expected_hash != options.configuration_hash:
            raise ApplicationError(
                ApplicationErrorCode.ANALYSIS_MODEL_CONFIGURATION_CHANGED,
                "model choices changed; reopen confirmation",
            )
        if profile_id is not None:
            profile = next((p for p in options.profiles if p.profile_id == profile_id), None)
            if profile is None:
                raise ApplicationError(
                    ApplicationErrorCode.ANALYSIS_MODEL_CONFIGURATION_INVALID,
                    "selected model unavailable",
                )
            return AnalysisModelPlan(
                mode="SINGLE_PROFILE",
                selected_profile_id=profile_id,
                bindings=tuple(
                    FrozenRoleModel(role=role, profile=profile) for role in ANALYSIS_ROLES
                ),
            )
        if options.missing_roles:
            raise ApplicationError(
                ApplicationErrorCode.ANALYSIS_MODEL_CONFIGURATION_INVALID,
                "analysis roles are not configured",
            )
        return AnalysisModelPlan(mode="ROLE_MAPPING", bindings=options.default_bindings)

    async def validate(self, plan: AnalysisModelPlan) -> None:
        profiles = {b.profile.profile_id: b.profile for b in plan.bindings}
        for profile in profiles.values():
            current = await self._settings.get_model_profile(profile.profile_id)
            if (
                current is None
                or not current.enabled
                or current.credential_ref is None
                or FrozenModelProfile.capture(current) != profile
            ):
                raise ApplicationError(
                    ApplicationErrorCode.ANALYSIS_MODEL_CONFIGURATION_CHANGED,
                    "frozen model configuration is no longer available",
                )
