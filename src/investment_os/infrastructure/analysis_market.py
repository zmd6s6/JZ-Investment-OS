"""Per-run adapter registry. Only explicitly selected and unchanged sources may run."""

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx

from investment_os.application.analysis_market import (
    AnalysisMarketPlan,
    FrozenMarketProfile,
    MarketAttempt,
    MarketAttemptEvent,
    MarketAuditFailure,
    MarketRecorder,
    RecordedMarketQuote,
)
from investment_os.application.analysis_progress import AnalysisCancelled
from investment_os.application.market_data import (
    MarketDataSourceFailure,
    MarketDataSourcePort,
    MarketQuote,
    QuoteRequest,
    ensure_daily_bar,
    ensure_price,
)
from investment_os.application.market_history import MarketHistory
from investment_os.application.provider_settings import DataProviderProfile, ProviderSettingsService
from investment_os.application.secrets import SecretStore
from investment_os.domain.errors import DomainError
from investment_os.infrastructure.tushare.market_data import (
    TUSHARE_PROVIDER_TYPE,
    TUSHARE_URL,
    TushareMarketDataAdapter,
)

SourceFactory = Callable[[DataProviderProfile, str, httpx.AsyncClient], MarketDataSourcePort]


def tushare_source(
    profile: DataProviderProfile, credential: str, client: httpx.AsyncClient
) -> MarketDataSourcePort:
    if profile.base_url.rstrip("/") != TUSHARE_URL:
        raise ValueError("Tushare adapter only supports the official endpoint")
    return TushareMarketDataAdapter(token=credential, client=client, profile_id=profile.id)


class PlannedMarketDataFactory:
    def __init__(
        self,
        settings: ProviderSettingsService,
        secrets: SecretStore,
        factories: dict[str, SourceFactory] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings, self.secrets = settings, secrets
        self.factories = (
            factories if factories is not None else {TUSHARE_PROVIDER_TYPE: tushare_source}
        )
        self.transport = transport

    @property
    def supported_types(self) -> frozenset[str]:
        return frozenset(self.factories)

    def for_plan(
        self,
        plan: AnalysisMarketPlan,
        record: Callable[[MarketAttempt], None],
        persist: MarketRecorder | None = None,
    ) -> "PlannedMarketData":
        return PlannedMarketData(self, plan, record, persist)


class PlannedMarketData:
    def __init__(
        self,
        factory: PlannedMarketDataFactory,
        plan: AnalysisMarketPlan,
        record: Callable[[MarketAttempt], None],
        persist: MarketRecorder | None = None,
    ) -> None:
        self._factory, self._plan, self._record = factory, plan, record
        self._persist = persist

    async def get_reference_quotes(
        self,
        instrument_ids: tuple[UUID, ...],
        *,
        as_of: datetime,
        instruments: dict[UUID, tuple[str, str, str]] | None = None,
    ) -> dict[UUID, MarketQuote]:
        mapping = instruments or {}
        pending = {
            i: QuoteRequest(
                i,
                *mapping.get(i, ("", "", "CNY")),
                include_history=i == self._plan.history_target_id,
            )
            for i in instrument_ids
        }
        found: dict[UUID, MarketQuote] = {}
        for rank, saved in enumerate(self._plan.profiles):
            if not pending:
                break
            batch = tuple(pending.values())
            common = dict(
                profile_id=saved.profile_id,
                name=saved.name,
                provider_type=saved.provider_type,
                rank=rank,
                queries=tuple(
                    f"{q.market}:{q.symbol}"
                    + (" / history:90-calendar-days:20-observations" if q.include_history else "")
                    for q in batch
                ),
            )
            attempt_id = uuid4()

            async def persist(attempt: MarketAttempt, identity: UUID = attempt_id) -> None:
                if self._persist is not None:
                    try:
                        await self._persist(
                            MarketAttemptEvent(
                                attempt_id=identity,
                                occurred_at=datetime.now(UTC),
                                attempt=attempt,
                            )
                        )
                    except AnalysisCancelled:
                        raise
                    except Exception:
                        raise MarketAuditFailure("market audit commit failed") from None

            async def finish(attempt: MarketAttempt) -> None:
                await persist(attempt)
                self._record(attempt)

            current = await self._factory.settings.get_data_profile(saved.profile_id)
            if (
                current is None
                or not current.enabled
                or FrozenMarketProfile.capture(current) != saved
            ):
                await finish(MarketAttempt(**common, status="CONFIGURATION_CHANGED"))
                break
            try:
                credential = (
                    await self._factory.secrets.get(current.credential_ref)
                    if current.credential_ref
                    else None
                )
            except RuntimeError:
                credential = None
            if not credential:
                await finish(MarketAttempt(**common, status="CREDENTIAL_MISSING"))
                break
            # Commit intent before entering adapter code. Failure must not trigger fallback.
            await persist(MarketAttempt(**common, status="STARTED"))
            try:
                async with httpx.AsyncClient(
                    timeout=current.timeout_seconds,
                    follow_redirects=False,
                    transport=self._factory.transport,
                ) as client:
                    source = self._factory.factories[current.provider_type](
                        current, credential, client
                    )
                    quotes = await asyncio.wait_for(
                        source.get_quotes(batch, as_of=as_of),
                        timeout=current.timeout_seconds
                        * (2 if any(q.include_history for q in batch) else 1),
                    )
                valid: dict[UUID, MarketQuote] = {}
                for identity, quote in quotes.items():
                    if (
                        identity not in pending
                        or quote.instrument_id != identity
                        or quote.as_of.tzinfo is None
                        or quote.as_of > as_of
                        or quote.currency != pending[identity].expected_currency
                    ):
                        raise ValueError("invalid quote identity, currency or time")
                    price = ensure_price(quote.reference_price)
                    if quote.history is not None and not pending[identity].include_history:
                        raise ValueError("history was not explicitly selected")
                    if pending[identity].include_history and quote.history is None:
                        quote = replace(
                            quote,
                            history=MarketHistory(
                                instrument_id=identity,
                                reference_at=quote.as_of,
                                status="UNAVAILABLE",
                                reason="NOT_PROVIDED",
                            ),
                        )
                    ensure_daily_bar(quote)
                    if quote.as_of + timedelta(days=current.retention_days) <= as_of:
                        raise ValueError("quote retention expired")
                    valid[identity] = replace(
                        quote,
                        reference_price=price,
                        source=saved.name,
                        source_rank=rank,
                        degraded=rank > 0,
                    )
                status = (
                    "SUCCEEDED" if len(valid) == len(batch) else "PARTIAL" if valid else "NO_DATA"
                )
            except (
                httpx.HTTPError,
                MarketDataSourceFailure,
                DomainError,
                TimeoutError,
                ValueError,
                TypeError,
                KeyError,
                IndexError,
            ):
                await finish(MarketAttempt(**common, status="FAILED"))
                continue
            await finish(
                MarketAttempt(
                    **common,
                    status=status,
                    returned_ids=tuple(valid),
                    observed_times=tuple(q.as_of for q in valid.values()),
                    quotes=tuple(
                        RecordedMarketQuote(
                            instrument_id=q.instrument_id,
                            reference_price=q.reference_price,
                            currency=q.currency,
                            as_of=q.as_of,
                        )
                        for q in valid.values()
                    ),
                )
            )
            found.update(valid)
            for identity in valid:
                pending.pop(identity)
        return found
