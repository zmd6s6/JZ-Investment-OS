"""Versioned daily scope/consent boundary; local observations never imply research permission."""

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Protocol, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from investment_os.application.analysis_runs import ANALYSIS_ROLES, SelectedData, SelectedModel
from investment_os.application.calendar_product import Confirmed
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.domain.agent import AgentRole

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Hash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
ExactCost = Annotated[str, StringConstraints(pattern=r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")]
Mode = Literal["LOCAL_STATUS_ONLY", "SCHEDULED_SHADOW"]


class DailyError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class DailyDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def utc_times(cls, value: object) -> object:
        return value.astimezone(UTC) if isinstance(value, datetime) else value


class DailyLimits(DailyDto):
    currency: Annotated[str, StringConstraints(pattern=r"^(?:[A-Z]{3}|NONE)$")]
    task_tokens: int = Field(strict=True, ge=0)
    day_tokens: int = Field(strict=True, ge=0)
    task_cost: ExactCost
    day_cost: ExactCost

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.task_tokens > self.day_tokens or Decimal(self.task_cost) > Decimal(self.day_cost):
            raise ValueError("daily limits must cover one task without exceeding the day")
        return self


class DailyDraft(DailyDto):
    schema_version: Literal["1.0"] = "1.0"
    name: Text
    mode: Mode
    market: Literal["SSE", "SZSE"]
    portfolio_id: UUID
    portfolio_instrument_ids: tuple[UUID, ...] = Field(max_length=100)
    watchlist_instrument_ids: tuple[UUID, ...] = Field(max_length=100)
    calendar_import_id: UUID
    coverage_start: date
    coverage_end: date
    frequency: Literal["DAILY_AFTER_EXPLICIT_CLOSE"]
    quote_source_name: Text
    evidence_source_names: tuple[Text, ...] = Field(max_length=10)
    retention_days: int = Field(strict=True, ge=1, le=3650)
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    model_profiles: dict[AgentRole, UUID]
    data_profile_ids: tuple[UUID, ...]
    limits: DailyLimits
    pause_method: Literal["DAILY_UI_PAUSE_OR_REVOKE"]
    complete_calendar_acknowledgement: Confirmed
    scope_acknowledgement: Confirmed
    local_only_acknowledgement: bool = Field(strict=True)
    model_egress_acknowledgement: bool = Field(strict=True)
    cost_acknowledgement: bool = Field(strict=True)

    @property
    def instrument_ids(self) -> tuple[UUID, ...]:
        return tuple(
            sorted(set(self.portfolio_instrument_ids + self.watchlist_instrument_ids), key=str)
        )

    @model_validator(mode="after")
    def closed_boundary(self) -> Self:
        if (
            self.coverage_end < self.coverage_start
            or (self.coverage_end - self.coverage_start).days > 365
        ):
            raise ValueError("explicit daily coverage must span at most 366 dates")
        if self.valid_until <= self.valid_from:
            raise ValueError("authorization expiry must follow its start")
        if not self.instrument_ids or len(self.instrument_ids) > 100:
            raise ValueError("explicit union scope must contain 1 to 100 instruments")
        if any(
            len(set(ids)) != len(ids)
            for ids in (self.portfolio_instrument_ids, self.watchlist_instrument_ids)
        ):
            raise ValueError("scope contains duplicate members")
        # External research billing has no typed per-call cost reservation today. This slice
        # explicitly authorizes no data profiles; local Evidence remains available.
        if self.data_profile_ids:
            raise ValueError("DAILY_EXTERNAL_RESEARCH_COST_BOUNDARY_UNAVAILABLE")
        if len(set(self.evidence_source_names)) != len(self.evidence_source_names):
            raise ValueError("duplicate local evidence source names")
        if self.mode == "LOCAL_STATUS_ONLY":
            if (
                self.model_profiles
                or not self.local_only_acknowledgement
                or self.model_egress_acknowledgement
                or self.cost_acknowledgement
                or self.limits.currency != "NONE"
                or self.limits.task_tokens
                or self.limits.day_tokens
                or Decimal(self.limits.task_cost)
                or Decimal(self.limits.day_cost)
            ):
                raise ValueError("local-only mode requires explicit zero providers and zero costs")
        elif (
            set(self.model_profiles) != set(ANALYSIS_ROLES)
            or self.local_only_acknowledgement
            or not self.model_egress_acknowledgement
            or not self.cost_acknowledgement
            or self.limits.currency == "NONE"
            or min(self.limits.task_tokens, self.limits.day_tokens) <= 0
            or not self.evidence_source_names
        ):
            raise ValueError("scheduled shadow requires complete explicit model/cost permission")
        return self


class DailySave(DailyDraft):
    request_id: UUID
    schedule_id: UUID
    expected_version: int = Field(strict=True, ge=0)


class DailyMode(DailyDto):
    request_id: UUID
    expected_version: int = Field(strict=True, ge=1)
    action: Literal["ENABLE", "PAUSE", "REVOKE"]
    confirmed: Confirmed


class DailyMember(DailyDto):
    instrument_id: UUID
    market: str
    symbol: str
    name: str
    in_portfolio: bool
    in_watchlist: bool


class DailyModelPrice(DailyDto):
    provider_type: Text
    base_url: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    version: Text
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
    input_token_price: ExactCost
    output_token_price: ExactCost
    effective_at: AwareDatetime


class DailyBudgetSnapshot(DailyDto):
    version: Text
    limits: DailyLimits


class DailyPrepared(DailyDto):
    command: DailySave
    calendar_hash: Hash
    calendar_source: Text
    calendar_version: Text
    members: tuple[DailyMember, ...]
    models: dict[AgentRole, SelectedModel]
    model_pricing: dict[AgentRole, DailyModelPrice]
    data_profiles: tuple[SelectedData, ...]
    budget_hash: Hash | None
    budget_snapshot: DailyBudgetSnapshot | None
    prepared_at: AwareDatetime
    input_hash: Hash

    @model_validator(mode="after")
    def exact_frozen_scope(self) -> Self:
        command = self.command
        if len(self.members) != len(command.instrument_ids) or {
            m.instrument_id for m in self.members
        } != set(command.instrument_ids):
            raise ValueError("DAILY_PREPARED_SCOPE_MISMATCH")
        for member in self.members:
            if (
                member.market != command.market
                or member.in_portfolio != (member.instrument_id in command.portfolio_instrument_ids)
                or member.in_watchlist != (member.instrument_id in command.watchlist_instrument_ids)
            ):
                raise ValueError("DAILY_PREPARED_SCOPE_MISMATCH")
        if self.data_profiles:
            raise ValueError("DAILY_EXTERNAL_RESEARCH_COST_BOUNDARY_UNAVAILABLE")
        if command.mode == "LOCAL_STATUS_ONLY":
            if (
                self.models
                or self.model_pricing
                or self.budget_hash is not None
                or self.budget_snapshot is not None
            ):
                raise ValueError("DAILY_LOCAL_PROVIDER_BOUNDARY")
        elif (
            set(self.models) != set(ANALYSIS_ROLES)
            or set(self.model_pricing) != set(ANALYSIS_ROLES)
            or self.budget_hash is None
            or self.budget_snapshot is None
            or any(
                model.profile_id != command.model_profiles[role]
                for role, model in self.models.items()
            )
        ):
            raise ValueError("DAILY_FROZEN_MODELS_OR_BUDGET_MISSING")
        return self


class DailyConfiguration(DailyDto):
    schema_version: Literal["1.0"] = "1.0"
    schedule_id: UUID
    revision_id: UUID
    version: int
    enabled: bool
    revoked: bool
    enabled_since: AwareDatetime | None
    prepared: DailyPrepared
    blocker: str | None = None
    auto_trade: Literal[False] = False


def assert_authorized(config: DailyConfiguration, *, version: int, now: datetime) -> None:
    if config.revoked:
        raise DailyError("DAILY_AUTHORIZATION_REVOKED")
    if not config.enabled:
        raise DailyError("DAILY_PAUSED")
    if config.version != version:
        raise DailyError("DAILY_VERSION_CHANGED")
    command = config.prepared.command
    if not command.valid_from <= now < command.valid_until:
        raise DailyError("DAILY_AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID")


class DailyEvidence(DailyDto):
    evidence_id: UUID
    instrument_id: UUID
    source_name: str
    content_hash: Hash
    observed_at: AwareDatetime
    effective_at: AwareDatetime
    available_at: AwareDatetime
    ingested_at: AwareDatetime
    expires_at: AwareDatetime | None
    quality_score: str

    def reason(self, as_of: datetime) -> str | None:
        if max(self.observed_at, self.effective_at, self.available_at, self.ingested_at) > as_of:
            return "FUTURE_OR_LATE_INGESTED"
        if self.expires_at is not None and self.expires_at <= as_of:
            return "EXPIRED"
        try:
            quality = Decimal(self.quality_score)
        except InvalidOperation:
            return "INVALID_QUALITY"
        if not quality.is_finite() or not 0 <= quality <= 1:
            return "INVALID_QUALITY"
        return None


class DailyEvidenceDiff(DailyDto):
    baseline_report_id: UUID | None
    baseline_status: Literal["FIRST_RUN_NO_BASELINE", "COMPARABLE_BASELINE"]
    visible_ids: tuple[UUID, ...]
    added_ids: tuple[UUID, ...]
    removed_ids: tuple[UUID, ...]
    excluded: dict[UUID, str]


def evidence_diff(
    evidence: tuple[DailyEvidence, ...],
    *,
    as_of: datetime,
    previous: tuple[UUID, ...],
    baseline_report_id: UUID | None,
) -> DailyEvidenceDiff:
    if as_of.utcoffset() is None:
        raise DailyError("DAILY_AS_OF_TIMEZONE_REQUIRED")
    ids = [row.evidence_id for row in evidence]
    if len(set(ids)) != len(ids):
        raise DailyError("DAILY_EVIDENCE_IDENTITY_CONFLICT")
    excluded = {row.evidence_id: reason for row in evidence if (reason := row.reason(as_of))}
    visible = set(ids) - excluded.keys()
    prior = set(previous)
    return DailyEvidenceDiff(
        baseline_report_id=baseline_report_id,
        baseline_status="COMPARABLE_BASELINE" if baseline_report_id else "FIRST_RUN_NO_BASELINE",
        visible_ids=tuple(sorted(visible, key=str)),
        added_ids=tuple(sorted(visible - prior, key=str)),
        removed_ids=tuple(sorted(prior - visible, key=str)),
        excluded=excluded,
    )


class DailySection(DailyDto):
    availability: Literal["PROVIDED", "NOT_PROVIDED", "DEGRADED"]
    messages: tuple[str, ...]
    evidence_ids: tuple[UUID, ...] = ()
    analysis_run_ids: tuple[UUID, ...] = ()


class DailyReport(DailyDto):
    schema_version: Literal["1.0"] = "1.0"
    report_id: UUID
    task_run_id: UUID
    schedule_id: UUID
    revision_id: UUID
    authorization_version: int
    business_date: date
    as_of: AwareDatetime
    recorded_at: AwareDatetime
    phase: Literal["LOCAL_COMPLETE", "SHADOW_PENDING", "SHADOW_COMPLETE", "DEGRADED"]
    mode: Mode
    scope_hash: Hash
    evidence_diff: DailyEvidenceDiff
    action_required: DailySection
    hold_watch: DailySection
    new_opportunity: DailySection
    risk_veto: DailySection
    approvals: DailySection
    data_job_degraded: DailySection
    auto_trade: Literal[False] = False


class DailySetupPort(Protocol):
    async def prepare(self, command: DailySave, now: datetime) -> DailyPrepared: ...


class DailyStorePort(Protocol):
    async def replay_save(self, command: DailySave) -> DailyConfiguration | None: ...
    async def save(self, prepared: DailyPrepared) -> DailyConfiguration: ...
    async def mode(self, schedule_id: UUID, command: DailyMode) -> DailyConfiguration: ...
    async def configurations(self) -> tuple[DailyConfiguration, ...]: ...
    async def reports(self, schedule_id: UUID | None = None) -> tuple[DailyReport, ...]: ...


class DailyRuntimeService:
    def __init__(self, setup: DailySetupPort, store: DailyStorePort):
        self.setup, self.store = setup, store

    async def save(self, command: DailySave) -> DailyConfiguration:
        prior = await self.store.replay_save(command)
        if prior:
            return prior
        now = datetime.now(UTC)
        prepared = await self.setup.prepare(command, now)
        if prepared.input_hash != fingerprint(
            prepared.model_dump(mode="json", exclude={"input_hash"})
        ):
            raise DailyError("DAILY_PREPARED_HASH_INVALID")
        return await self.store.save(prepared)
