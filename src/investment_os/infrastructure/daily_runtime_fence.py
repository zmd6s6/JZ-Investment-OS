"""Per-call SQL authorization fence; pause/revoke/cancel linearize against real egress."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.analysis_runs import AnalysisQueuedInput
from investment_os.application.daily_runtime import DailyError, assert_authorized
from investment_os.application.llm_gateway import (
    LLMGatewayPort,
    LLMGatewayRequest,
    LLMGatewayResponse,
)
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.application.runtime_authorization import (
    RuntimeAuthorizationRef,
    RuntimeEgressBlocked,
)
from investment_os.application.schedule import MarketVenue
from investment_os.infrastructure.daily_runtime_models import (
    DailyAnalysisIntentRecord,
    DailyConfigurationRecord,
    DailyExecutionRecord,
)
from investment_os.infrastructure.daily_runtime_setup import (
    SqlDailySetup,
    capture_calendar,
    capture_scope,
)
from investment_os.infrastructure.daily_runtime_store import configuration
from investment_os.infrastructure.persistence.analysis_models import AnalysisRunRecord


class SqlDailyAuthorizationFence:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        setup: SqlDailySetup,
        *,
        now: Callable[[], datetime] | None = None,
    ):
        self.sessions, self.setup = sessions, setup
        self.now = now or (lambda: datetime.now(UTC))
        self._current: ContextVar[Callable[[], None] | None] = ContextVar(
            "daily_model_final_egress", default=None
        )

    @asynccontextmanager
    async def permit(
        self, run_id: UUID, lease: UUID, queued: AnalysisQueuedInput, *, lock_analysis: bool
    ) -> AsyncIterator[Callable[[], None]]:
        async with self.sessions() as session, session.begin():
            intent = await session.get(DailyAnalysisIntentRecord, queued.command.request_id)
            raw = getattr(queued.command, "runtime_authorization", None)
            if intent is None and raw is None:
                yield lambda: None  # Existing interactive analysis retains its separate consent.
                return
            if raw is None or intent is None:
                raise DailyError("DAILY_AUTHORIZATION_REFERENCE_MISSING")
            try:
                reference = RuntimeAuthorizationRef.model_validate(raw)
            except ValueError:
                raise DailyError("DAILY_AUTHORIZATION_REFERENCE_INVALID") from None
            execution = await session.get(DailyExecutionRecord, intent.execution_id)
            if execution is None:
                raise DailyError("DAILY_EXECUTION_REFERENCE_MISSING")
            pointer = await session.get(
                DailyConfigurationRecord, execution.schedule_id, with_for_update={"read": True}
            )
            if pointer is None:
                raise DailyError("DAILY_AUTHORIZATION_REFERENCE_MISSING")
            config = await configuration(session, pointer)
            assert_authorized(config, version=execution.authorization_version, now=self.now())
            expected = config.prepared
            command = expected.command
            if (
                reference.intent_id != intent.id
                or intent.id != queued.command.request_id
                or reference.schedule_id != pointer.id
                or reference.revision_id != pointer.revision_id
                or reference.revision_id != intent.revision_id
                or reference.revision_id != execution.revision_id
                or reference.authorization_version != execution.authorization_version
                or reference.authorization_hash != expected.input_hash
                or command.mode != "SCHEDULED_SHADOW"
                or queued.command.portfolio_id != command.portfolio_id
                or queued.command.instrument_id not in command.instrument_ids
                or queued.command.instrument_id != intent.instrument_id
                or queued.command.market_source_name != command.quote_source_name
                or queued.models != expected.models
                or queued.budget_hash != expected.budget_hash
                or queued.data_profiles
                or queued.command.data_profile_ids
                or queued.command.allow_data_calls
                or fingerprint(queued.command.model_dump(mode="json")) != intent.request_hash
                or fingerprint(intent.command_json) != intent.request_hash
                or {h.instrument_id for h in queued.valuation.input_snapshot.holdings}
                != set(command.portfolio_instrument_ids)
            ):
                raise DailyError("DAILY_FROZEN_SCOPE_OR_COMMAND_MISMATCH")
            if await capture_scope(session, command, lock=True) != expected.members:
                raise DailyError("DAILY_SCOPE_CHANGED")
            calendar, _ = await capture_calendar(session, command, lock=True)
            if calendar.content_hash != expected.calendar_hash:
                raise DailyError("DAILY_CALENDAR_CHANGED_OR_MISSING")
            await self.setup.verify_profiles(expected, self.now())
            if lock_analysis:
                # Installed inside PinnedAnalysisGateway, after its FOR UPDATE step writes.
                # Holding this shared row lock outside Pinned would deadlock that same stage.
                active = await session.get(
                    AnalysisRunRecord, run_id, with_for_update={"read": True}
                )
                if (
                    active is None
                    or active.lease_id != lease
                    or active.status != "RUNNING"
                    or active.cancel_requested
                    or active.request_id != intent.id
                    or active.request_hash != intent.request_hash
                ):
                    raise DailyError("DAILY_ANALYSIS_CANCELLED_OR_LEASE_CHANGED")

            def final_check() -> None:
                current = self.now()
                assert_authorized(config, version=execution.authorization_version, now=current)
                if (
                    current.astimezone(MarketVenue(command.market).timezone).date()
                    != execution.business_date
                ):
                    raise DailyError("DAILY_MISSED_SESSION_RESEARCH_FORBIDDEN")

            final_check()
            yield final_check

    def prepare_permit(
        self, run_id: UUID, lease: UUID, queued: AnalysisQueuedInput
    ) -> AbstractAsyncContextManager[Callable[[], None]]:
        return self.permit(run_id, lease, queued, lock_analysis=False)

    def wrap_model(
        self, run_id: UUID, lease: UUID, queued: AnalysisQueuedInput, delegate: LLMGatewayPort
    ) -> LLMGatewayPort:
        return DailyGuardedGateway(self, run_id, lease, queued, delegate)

    def before_model_egress(self) -> None:
        check = self._current.get()
        if check is None:
            raise RuntimeEgressBlocked("DAILY_FINAL_EGRESS_CONTEXT_MISSING")
        try:
            check()
        except DailyError as exc:
            raise RuntimeEgressBlocked(exc.code) from None


class DailyGuardedGateway:
    def __init__(
        self,
        fence: SqlDailyAuthorizationFence,
        run_id: UUID,
        lease: UUID,
        queued: AnalysisQueuedInput,
        delegate: LLMGatewayPort,
    ):
        self.fence, self.run_id, self.lease, self.queued, self.delegate = (
            fence,
            run_id,
            lease,
            queued,
            delegate,
        )

    async def complete(self, request: LLMGatewayRequest) -> LLMGatewayResponse:
        try:
            async with self.fence.permit(
                self.run_id, self.lease, self.queued, lock_analysis=True
            ) as check:
                token = self.fence._current.set(check)
                try:
                    return await self.delegate.complete(request)
                finally:
                    self.fence._current.reset(token)
        except DailyError as exc:
            raise RuntimeEgressBlocked(exc.code) from None
