"""Explicit ordered market sources for one analysis; no implicit provider fallback."""

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from investment_os.application.analysis_models import digest
from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.market_data import MarketDataPort
from investment_os.application.provider_settings import DataProviderProfile, ProviderSettingsService


class FrozenMarketProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile_id: UUID
    name: str
    provider_type: str
    timeout_seconds: int
    retention_days: int
    configuration_hash: str

    @classmethod
    def capture(cls, profile: DataProviderProfile) -> "FrozenMarketProfile":
        values = asdict(profile)
        for key in ("credential_ref", "enabled"):
            values.pop(key)
        return cls(
            profile_id=profile.id,
            name=profile.name,
            provider_type=profile.provider_type,
            timeout_seconds=profile.timeout_seconds,
            retention_days=profile.retention_days,
            configuration_hash=digest(values),
        )


class AnalysisMarketPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0"] = "1.0"
    profiles: tuple[FrozenMarketProfile, ...] = Field(default=(), max_length=10)

    @model_validator(mode="after")
    def unique_profiles(self) -> "AnalysisMarketPlan":
        if len({p.profile_id for p in self.profiles}) != len(self.profiles):
            raise ValueError("market profiles must not repeat")
        return self


class AnalysisMarketOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0"] = "1.0"
    configuration_hash: str
    profiles: tuple[FrozenMarketProfile, ...]


class RecordedMarketQuote(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    instrument_id: UUID
    reference_price: Decimal
    currency: str
    as_of: datetime


class MarketAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile_id: UUID
    name: str
    provider_type: str
    rank: int
    status: Literal[
        "SUCCEEDED", "PARTIAL", "NO_DATA", "FAILED", "CONFIGURATION_CHANGED", "CREDENTIAL_MISSING"
    ]
    queries: tuple[str, ...]
    returned_ids: tuple[UUID, ...] = ()
    observed_times: tuple[datetime, ...] = ()
    quotes: tuple[RecordedMarketQuote, ...] = ()


class AnalysisMarketFactory(Protocol):
    def for_plan(
        self, plan: AnalysisMarketPlan, record: Callable[[MarketAttempt], None]
    ) -> MarketDataPort: ...


class AnalysisMarketConfiguration:
    def __init__(self, settings: ProviderSettingsService, supported_types: frozenset[str]) -> None:
        self._settings, self._types = settings, supported_types

    async def options(self) -> AnalysisMarketOptions:
        profiles = tuple(
            sorted(
                (
                    FrozenMarketProfile.capture(p)
                    for p in await self._settings.list_data_profiles()
                    if p.enabled and p.credential_ref is not None and p.provider_type in self._types
                ),
                key=lambda p: str(p.profile_id),
            )
        )
        return AnalysisMarketOptions(
            configuration_hash=digest([p.model_dump(mode="json") for p in profiles]),
            profiles=profiles,
        )

    async def freeze(self, ids: tuple[UUID, ...], expected_hash: str | None) -> AnalysisMarketPlan:
        if not ids and expected_hash is None:
            return AnalysisMarketPlan()
        options = await self.options()
        if expected_hash is not None and expected_hash != options.configuration_hash:
            raise ApplicationError(
                ApplicationErrorCode.ANALYSIS_MARKET_CONFIGURATION_CHANGED, "market choices changed"
            )
        available = {p.profile_id: p for p in options.profiles}
        if len(ids) > 10 or len(ids) != len(set(ids)) or any(i not in available for i in ids):
            raise ApplicationError(
                ApplicationErrorCode.ANALYSIS_MARKET_CONFIGURATION_INVALID, "invalid market choice"
            )
        return AnalysisMarketPlan(profiles=tuple(available[i] for i in ids))

    async def validate(self, plan: AnalysisMarketPlan) -> None:
        for saved in plan.profiles:
            current = await self._settings.get_data_profile(saved.profile_id)
            if (
                current is None
                or not current.enabled
                or current.credential_ref is None
                or current.provider_type not in self._types
                or FrozenMarketProfile.capture(current) != saved
            ):
                raise ApplicationError(
                    ApplicationErrorCode.ANALYSIS_MARKET_CONFIGURATION_CHANGED,
                    "frozen market source unavailable",
                )
