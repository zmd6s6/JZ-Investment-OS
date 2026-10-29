"""Local SQL/profile capture for a paused daily authorization; never contacts a provider."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.analysis_configuration import (
    budget_hash,
    profile_hash,
    require_safe_profile_url,
)
from investment_os.application.analysis_runs import ANALYSIS_ROLES, SelectedModel
from investment_os.application.calendar_product import CalendarSessionInput, calendar_hash
from investment_os.application.daily_runtime import (
    DailyBudgetSnapshot,
    DailyError,
    DailyLimits,
    DailyMember,
    DailyModelPrice,
    DailyPrepared,
    DailySave,
)
from investment_os.application.llm_budget import LLMBudgetService
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.application.provider_settings import (
    ModelProviderProfile,
    ProviderSettingsService,
)
from investment_os.application.schedule import MarketVenue
from investment_os.domain.agent import AgentRole
from investment_os.infrastructure.persistence.calendar_models import (
    CalendarConfigurationRecord,
    CalendarImportRecord,
    MarketSessionRecord,
)
from investment_os.infrastructure.persistence.models import (
    InstrumentRecord,
    PortfolioRecord,
    PositionRecord,
    WatchlistItemRecord,
)


async def capture_scope(
    session: AsyncSession, command: DailySave, *, lock: bool = False
) -> tuple[DailyMember, ...]:
    portfolio = await session.get(
        PortfolioRecord, command.portfolio_id, with_for_update={"read": True} if lock else None
    )
    if portfolio is None or portfolio.status != "ACTIVE" or portfolio.base_currency != "CNY":
        raise DailyError("DAILY_PORTFOLIO_UNAVAILABLE_OR_CURRENCY_UNSUPPORTED")
    positions = select(PositionRecord).where(PositionRecord.portfolio_id == command.portfolio_id)
    if lock:
        positions = positions.with_for_update(read=True)
    rows = (await session.scalars(positions)).all()
    # AnalysisStart's valuation sends the whole selected portfolio. Permission must cover
    # precisely that entire portfolio, not only the target instrument.
    if {row.instrument_id for row in rows} != set(command.portfolio_instrument_ids):
        raise DailyError("DAILY_PORTFOLIO_SCOPE_CHANGED")
    watches = select(WatchlistItemRecord).where(
        WatchlistItemRecord.instrument_id.in_(command.watchlist_instrument_ids)
    )
    if lock:
        watches = watches.with_for_update(read=True)
    selected = (await session.scalars(watches)).all()
    if {row.instrument_id for row in selected} != set(command.watchlist_instrument_ids):
        raise DailyError("DAILY_WATCHLIST_SCOPE_CHANGED")
    instruments = select(InstrumentRecord).where(InstrumentRecord.id.in_(command.instrument_ids))
    if lock:
        instruments = instruments.with_for_update(read=True)
    records = (await session.scalars(instruments)).all()
    if {row.id for row in records} != set(command.instrument_ids):
        raise DailyError("DAILY_INSTRUMENT_MISSING")
    if any(
        row.exchange != command.market or row.currency != "CNY" or row.status != "ACTIVE"
        for row in records
    ):
        raise DailyError("DAILY_MARKET_OR_IDENTITY_MISMATCH")
    return tuple(
        DailyMember(
            instrument_id=row.id,
            market=row.exchange,
            symbol=row.symbol,
            name=row.name,
            in_portfolio=row.id in command.portfolio_instrument_ids,
            in_watchlist=row.id in command.watchlist_instrument_ids,
        )
        for row in sorted(records, key=lambda item: str(item.id))
    )


async def capture_calendar(
    session: AsyncSession, command: DailySave, *, lock: bool = False
) -> tuple[CalendarImportRecord, tuple[CalendarSessionInput, ...]]:
    statement = select(CalendarConfigurationRecord).where(
        CalendarConfigurationRecord.venue == command.market
    )
    if lock:
        statement = statement.with_for_update(read=True)
    current = await session.scalar(statement)
    record = await session.get(CalendarImportRecord, command.calendar_import_id)
    if (
        current is None
        or record is None
        or current.active_import_id != record.id
        or record.venue != command.market
    ):
        raise DailyError("DAILY_CALENDAR_CHANGED_OR_MISSING")
    rows = (
        await session.scalars(
            select(MarketSessionRecord)
            .where(MarketSessionRecord.import_id == record.id)
            .order_by(MarketSessionRecord.business_date)
        )
    ).all()
    sessions = tuple(
        CalendarSessionInput(business_date=row.business_date, close_at_utc=row.close_at_utc)
        for row in rows
    )
    venue = MarketVenue(command.market)
    if (
        not sessions
        or len(sessions) > 1000
        or any(
            row.close_at_utc.astimezone(venue.timezone).date() != row.business_date
            for row in sessions
        )
        or calendar_hash(venue, record.source_name, record.source_version, sessions)
        != record.content_hash
    ):
        raise DailyError("DAILY_CALENDAR_INVALID")
    if (
        sessions[0].business_date > command.coverage_start
        or sessions[-1].business_date < command.coverage_end
    ):
        raise DailyError("DAILY_CALENDAR_COVERAGE_OUTSIDE_SOURCE")
    # STATUS_ONLY enabled is deliberately irrelevant to this separate authorization.
    return record, sessions


class SqlDailySetup:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        providers: ProviderSettingsService,
        budget: LLMBudgetService,
    ):
        self.sessions, self.providers, self.budget = sessions, providers, budget

    async def capture_profiles(
        self, command: DailySave, now: datetime
    ) -> tuple[
        dict[AgentRole, SelectedModel],
        dict[AgentRole, DailyModelPrice],
        str | None,
        DailyBudgetSnapshot | None,
    ]:
        if command.mode == "LOCAL_STATUS_ONLY":
            return {}, {}, None, None
        policy = await self.budget.policy()
        if policy is None:
            raise DailyError("DAILY_BUDGET_UNAVAILABLE")
        allowed = command.limits
        if (
            policy.currency != allowed.currency
            or policy.task_token_limit > allowed.task_tokens
            or policy.daily_token_limit > allowed.day_tokens
            or policy.task_cost_limit > Decimal(allowed.task_cost)
            or policy.daily_cost_limit > Decimal(allowed.day_cost)
        ):
            raise DailyError("DAILY_BUDGET_EXCEEDS_AUTHORIZATION")
        models: dict[AgentRole, SelectedModel] = {}
        pricing: dict[AgentRole, DailyModelPrice] = {}
        cache: dict[UUID, ModelProviderProfile] = {}
        for role in ANALYSIS_ROLES:
            identifier = command.model_profiles[role]
            model = cache.get(identifier) or await self.providers.get_model_profile(identifier)
            if (
                model is None
                or not model.enabled
                or model.credential_ref is None
                or model.provider_type != "OPENAI_COMPATIBLE"
            ):
                raise DailyError("DAILY_MODEL_PROFILE_UNAVAILABLE")
            require_safe_profile_url(model.base_url)
            if (
                model.pricing_version is None
                or model.pricing_currency != policy.currency
                or model.input_token_price is None
                or model.output_token_price is None
                or not model.input_token_price.is_finite()
                or not model.output_token_price.is_finite()
                or min(model.input_token_price, model.output_token_price) < 0
                or model.pricing_effective_at is None
                or model.pricing_effective_at > now
                or model.max_tokens > allowed.task_tokens
            ):
                raise DailyError("DAILY_MODEL_PRICING_OR_TOKEN_BOUNDARY_INVALID")
            cache[identifier] = model
            models[role] = SelectedModel(
                profile_id=model.id,
                name=model.name,
                model_name=model.model_name,
                config_hash=profile_hash(model),
                timeout_seconds=model.timeout_seconds,
                max_tokens=model.max_tokens,
            )
            pricing[role] = DailyModelPrice(
                provider_type=model.provider_type,
                base_url=model.base_url,
                version=model.pricing_version,
                currency=policy.currency,
                input_token_price=format(model.input_token_price, "f"),
                output_token_price=format(model.output_token_price, "f"),
                effective_at=model.pricing_effective_at,
            )
        snapshot = DailyBudgetSnapshot(
            version=policy.version,
            limits=DailyLimits(
                currency=policy.currency,
                task_tokens=policy.task_token_limit,
                day_tokens=policy.daily_token_limit,
                task_cost=format(policy.task_cost_limit, "f"),
                day_cost=format(policy.daily_cost_limit, "f"),
            ),
        )
        return models, pricing, budget_hash(policy), snapshot

    async def prepare(self, command: DailySave, now: datetime) -> DailyPrepared:
        async with self.sessions() as session:
            members = await capture_scope(session, command)
            calendar, _ = await capture_calendar(session, command)
        models, prices, budget, snapshot = await self.capture_profiles(command, now)
        prepared = DailyPrepared(
            command=command,
            calendar_hash=calendar.content_hash,
            calendar_source=calendar.source_name,
            calendar_version=calendar.source_version,
            members=members,
            models=models,
            model_pricing=prices,
            data_profiles=(),
            budget_hash=budget,
            budget_snapshot=snapshot,
            prepared_at=now,
            input_hash="0" * 64,
        )
        return prepared.model_copy(
            update={
                "input_hash": fingerprint(prepared.model_dump(mode="json", exclude={"input_hash"}))
            }
        )

    async def verify_profiles(self, prepared: DailyPrepared, now: datetime) -> None:
        models, prices, budget, snapshot = await self.capture_profiles(prepared.command, now)
        if (models, prices, budget, snapshot) != (
            prepared.models,
            prepared.model_pricing,
            prepared.budget_hash,
            prepared.budget_snapshot,
        ):
            raise DailyError("DAILY_PROVIDER_OR_BUDGET_CHANGED")
