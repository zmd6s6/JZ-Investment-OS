"""Explicit source selection, immutable routing and per-run audit; synthetic only."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from test_openai_compatible_llm import MemoryProviderSettingsPort, MemorySecretStore

from investment_os.application.analysis_market import (
    AnalysisMarketConfiguration,
    AnalysisMarketPlan,
    MarketAuditFailure,
)
from investment_os.application.errors import ApplicationError
from investment_os.application.market_data import MarketDataSourceFailure, MarketQuote, QuoteRequest
from investment_os.application.provider_settings import DataProviderProfile, ProviderSettingsService
from investment_os.infrastructure.analysis_market import PlannedMarketDataFactory
from investment_os.infrastructure.tushare.market_data import TushareMarketDataAdapter

NOW = datetime(2026, 10, 20, 8, tzinfo=UTC)


class Store(MemoryProviderSettingsPort):
    def __init__(self):
        super().__init__()
        self.data = {}

    async def list_data_profiles(self):
        return list(self.data.values())

    async def get_data_profile(self, identity):
        return self.data.get(identity)


def configured():
    port, secrets = Store(), MemorySecretStore()
    settings = ProviderSettingsService(port, secrets)
    return (
        port,
        secrets,
        settings,
        AnalysisMarketConfiguration(settings, frozenset({"TUSHARE_MARKET"})),
    )


def add(port, secrets, name="合成行情", **changes):
    profile = DataProviderProfile(
        uuid4(), name, "TUSHARE_MARKET", "https://api.tushare.pro", uuid4(), 5, True, 365
    )
    profile = replace(profile, **changes)
    port.data[profile.id] = profile
    secrets.values[profile.credential_ref] = "synthetic-only"
    return profile


async def test_market_options_filter_and_freeze_exact_order_without_secrets():
    port, secrets, _, config = configured()
    first, second = add(port, secrets), add(port, secrets, "第二源")
    add(port, secrets, provider_type="BOCHA")
    add(port, secrets, enabled=False)
    add(port, secrets, credential_ref=None)
    options = await config.options()
    assert {p.profile_id for p in options.profiles} == {first.id, second.id}
    plan = await config.freeze((second.id, first.id), options.configuration_hash)
    assert [p.profile_id for p in plan.profiles] == [second.id, first.id]
    serialized = plan.model_dump_json()
    assert "synthetic-only" not in serialized and "https://" not in serialized
    assert "credential_ref" not in serialized
    for ids in ((first.id, first.id), (uuid4(),), tuple(uuid4() for _ in range(11))):
        with pytest.raises(ApplicationError, match="invalid market choice"):
            await config.freeze(ids, None)
    port.data[first.id] = replace(first, timeout_seconds=6)
    with pytest.raises(ApplicationError, match="market choices changed"):
        await config.freeze((first.id,), options.configuration_hash)


@pytest.mark.parametrize("change", ["disable", "delete", "endpoint", "credential", "type"])
async def test_market_frozen_config_fails_closed(change):
    port, secrets, _, config = configured()
    profile = add(port, secrets)
    plan = await config.freeze((profile.id,), None)
    if change == "delete":
        del port.data[profile.id]
    else:
        patch = {
            "disable": {"enabled": False},
            "endpoint": {"base_url": "https://different.example.test"},
            "credential": {"credential_ref": None},
            "type": {"provider_type": "BOCHA"},
        }[change]
        port.data[profile.id] = replace(profile, **patch)
    with pytest.raises(ApplicationError, match="frozen market source unavailable"):
        await config.validate(plan)


async def test_market_empty_selection_does_not_read_settings_or_sources():
    port, secrets, settings, config = configured()
    add(port, secrets)

    async def forbidden():
        raise AssertionError("empty choice must not read settings")

    settings.list_data_profiles = forbidden
    assert await config.freeze((), None) == AnalysisMarketPlan()
    attempts = []
    reader = PlannedMarketDataFactory(settings, secrets, {}).for_plan(
        AnalysisMarketPlan(), attempts.append
    )
    assert await reader.get_reference_quotes((uuid4(),), as_of=NOW) == {}
    assert attempts == []


class Source:
    name = "SYNTHETIC_TEST_ONLY"

    def __init__(self, operation):
        self.operation = operation

    async def get_quotes(self, batch, *, as_of):
        return await self.operation(batch, as_of)


def quote(identity, **changes):
    value = MarketQuote(
        identity, Decimal("12.3456789"), "CNY", NOW, "SYNTHETIC", volatility=Decimal("0.20")
    )
    return replace(value, **changes)


async def test_market_chain_only_selected_order_and_partial_requests_are_audited():
    port, secrets, settings, config = configured()
    one, two, unused = (add(port, secrets, str(i)) for i in range(3))
    a, b = uuid4(), uuid4()
    calls, attempts = [], []

    def factory(profile, credential, client):
        async def read(batch, as_of):
            calls.append((profile.id, tuple(q.instrument_id for q in batch)))
            return (
                {a: quote(a, reference_price="12.3456789")}
                if profile.id == one.id
                else {b: quote(b)}
            )

        return Source(read)

    plan = await config.freeze((one.id, two.id, unused.id), None)
    reader = PlannedMarketDataFactory(settings, secrets, {"TUSHARE_MARKET": factory}).for_plan(
        plan, attempts.append
    )
    result = await reader.get_reference_quotes((a, b), as_of=NOW)
    assert calls == [(one.id, (a, b)), (two.id, (b,))]
    assert [v.status for v in attempts] == ["PARTIAL", "SUCCEEDED"]
    assert result[a].source == one.name and not result[a].degraded
    assert isinstance(result[a].reference_price, Decimal)
    assert result[b].source_rank == 1 and result[b].degraded
    assert attempts[1].quotes[0].reference_price == Decimal("12.3456789")
    assert attempts[1].quotes[0].as_of == NOW


@pytest.mark.parametrize("mode", ["failure", "empty", "changed", "missing"])
async def test_market_failure_falls_back_but_configuration_or_missing_credential_stops(mode):
    port, secrets, settings, config = configured()
    one, two, unselected = (add(port, secrets, str(i)) for i in range(3))
    identity, calls, attempts = uuid4(), [], []
    plan = await config.freeze((one.id, two.id), None)
    if mode == "changed":
        port.data[one.id] = replace(one, enabled=False)
    if mode == "missing":
        secrets.values.clear()

    def factory(profile, credential, client):
        async def read(batch, as_of):
            calls.append(profile.id)
            if profile.id == one.id:
                if mode == "failure":
                    raise MarketDataSourceFailure("sensitive upstream body must not be recorded")
                return {}
            return {identity: quote(identity)}

        return Source(read)

    reader = PlannedMarketDataFactory(settings, secrets, {"TUSHARE_MARKET": factory}).for_plan(
        plan, attempts.append
    )
    values = await reader.get_reference_quotes((identity,), as_of=NOW)
    expected = {
        "failure": "FAILED",
        "empty": "NO_DATA",
        "changed": "CONFIGURATION_CHANGED",
        "missing": "CREDENTIAL_MISSING",
    }
    assert attempts[0].status == expected[mode]
    assert unselected.id not in calls
    if mode in {"changed", "missing"}:
        assert calls == [] and values == {}
    else:
        assert calls == [one.id, two.id] and identity in values
    assert "sensitive" not in str(attempts)


@pytest.mark.parametrize(
    "bad", ["future", "naive", "currency", "identity", "float", "zero", "nan", "expired"]
)
async def test_market_invalid_quote_never_enters_valuation(bad):
    port, secrets, settings, config = configured()
    profile = add(port, secrets)
    identity, attempts = uuid4(), []
    changes = {
        "future": {"as_of": NOW + timedelta(seconds=1)},
        "naive": {"as_of": NOW.replace(tzinfo=None)},
        "currency": {"currency": "USD"},
        "identity": {"instrument_id": uuid4()},
        "float": {"reference_price": 1.5},
        "zero": {"reference_price": Decimal("0")},
        "nan": {"reference_price": Decimal("NaN")},
        "expired": {"as_of": NOW - timedelta(days=365)},
    }[bad]

    async def read(batch, as_of):
        return {identity: quote(identity, **changes)}

    reader = PlannedMarketDataFactory(
        settings, secrets, {"TUSHARE_MARKET": lambda *args: Source(read)}
    ).for_plan(await config.freeze((profile.id,), None), attempts.append)
    assert await reader.get_reference_quotes((identity,), as_of=NOW) == {}
    assert attempts[0].status == "FAILED" and not attempts[0].quotes


async def test_concurrent_market_runs_do_not_share_attempt_audit():
    port, secrets, settings, config = configured()
    profiles = [add(port, secrets, str(i)) for i in range(2)]

    def factory(profile, credential, client):
        async def read(batch, as_of):
            await asyncio.sleep(0)
            return {q.instrument_id: quote(q.instrument_id) for q in batch}

        return Source(read)

    factory = PlannedMarketDataFactory(settings, secrets, {"TUSHARE_MARKET": factory})

    async def run(profile):
        audit = []
        await factory.for_plan(
            await config.freeze((profile.id,), None), audit.append
        ).get_reference_quotes((uuid4(),), as_of=NOW)
        return audit

    results = await asyncio.gather(*(run(p) for p in profiles))
    assert [[a.profile_id for a in audit] for audit in results] == [[p.id] for p in profiles]


@pytest.mark.parametrize("fail_at", ["STARTED", "NO_DATA"])
async def test_audit_failure_blocks_unrecorded_call_or_fallback(fail_at):
    port, secrets, settings, config = configured()
    profiles = [add(port, secrets, str(i)) for i in range(2)]
    calls, committed = [], []

    async def persist(event):
        if event.attempt.status == fail_at:
            raise ValueError("sensitive database error")
        committed.append(event)

    def factory(profile, *args):
        async def read(batch, as_of):
            assert committed[-1].attempt.status == "STARTED"
            calls.append(profile.id)
            return {}

        return Source(read)

    reader = PlannedMarketDataFactory(settings, secrets, {"TUSHARE_MARKET": factory}).for_plan(
        await config.freeze(tuple(p.id for p in profiles), None),
        lambda a: None,
        persist,
    )
    with pytest.raises(MarketAuditFailure, match="market audit commit failed") as failure:
        await reader.get_reference_quotes((uuid4(),), as_of=NOW)
    assert "sensitive" not in str(failure.value)
    assert calls == ([] if fail_at == "STARTED" else [profiles[0].id])
    assert [e.attempt.status for e in committed] == ([] if fail_at == "STARTED" else ["STARTED"])


async def test_process_cancel_keeps_committed_start_without_manufacturing_failure():
    port, secrets, settings, config = configured()
    profile = add(port, secrets)
    committed, completed = [], []

    async def persist(event):
        committed.append(event)

    async def interrupted(batch, as_of):
        raise asyncio.CancelledError()

    reader = PlannedMarketDataFactory(
        settings, secrets, {"TUSHARE_MARKET": lambda *a: Source(interrupted)}
    ).for_plan(
        await config.freeze((profile.id,), None),
        completed.append,
        persist,
    )
    with pytest.raises(asyncio.CancelledError):
        await reader.get_reference_quotes((uuid4(),), as_of=NOW)
    assert [e.attempt.status for e in committed] == ["STARTED"]
    assert completed == []


@pytest.mark.parametrize("hour,available", [(6, False), (7, True)])
async def test_tushare_daily_close_available_only_at_shanghai_close(hour, available):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "fields": ["ts_code", "trade_date", "close"],
                    "items": [["600519.SH", "20261020", 1500.5]],
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = TushareMarketDataAdapter(token="synthetic", client=client)
        identity = uuid4()
        values = await adapter.get_quotes(
            (QuoteRequest(identity, "SSE", "600519", "CNY"),), as_of=NOW.replace(hour=hour)
        )
    assert bool(values) == available
    if available:
        assert values[identity].reference_price == Decimal("1500.5")
        assert values[identity].as_of == NOW.replace(hour=7)


@pytest.mark.parametrize(
    "body",
    [
        {"code": 1, "msg": "sensitive"},
        {"code": 0},
        {"code": 0, "data": {"items": [], "fields": []}},
        {
            "code": 0,
            "data": {"fields": ["ts_code", "trade_date", "close"], "items": [["600519.SH"]]},
        },
    ],
)
async def test_tushare_bad_response_is_failure_not_no_data(body):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    ) as client:
        adapter = TushareMarketDataAdapter(token="synthetic", client=client)
        with pytest.raises(MarketDataSourceFailure) as failure:
            await adapter.get_quotes((QuoteRequest(uuid4(), "SSE", "600519", "CNY"),), as_of=NOW)
    assert "sensitive" not in str(failure.value)


@pytest.mark.parametrize(
    "price,day", [("not-a-number", "20261020"), ("-2", "20261020"), ("12", "invalid-day")]
)
async def test_tushare_invalid_price_or_date_is_sanitized_failure(price, day):
    body = {
        "code": 0,
        "data": {
            "fields": ["ts_code", "trade_date", "close"],
            "items": [["600519.SH", day, price]],
        },
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    ) as client:
        with pytest.raises(MarketDataSourceFailure):
            await TushareMarketDataAdapter(token="synthetic", client=client).get_quotes(
                (QuoteRequest(uuid4(), "SSE", "600519", "CNY"),), as_of=NOW
            )


async def test_tushare_query_uses_market_business_date_not_utc_date():
    import json

    calls = []

    def handler(request):
        calls.append(json.loads(request.content)["params"]["trade_date"])
        return httpx.Response(
            200,
            json={"code": 0, "data": {"fields": ["ts_code", "trade_date", "close"], "items": []}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert (
            await TushareMarketDataAdapter(token="synthetic", client=client).get_quotes(
                (QuoteRequest(uuid4(), "SSE", "600519", "CNY"),), as_of=NOW.replace(hour=16)
            )
            == {}
        )
    assert calls == ["20261021"]


async def test_tushare_unsupported_currency_or_market_never_calls_network():
    def forbidden(request):
        raise AssertionError("no cross currency or market conversion")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        adapter = TushareMarketDataAdapter(token="synthetic", client=client)
        assert (
            await adapter.get_quotes(
                (
                    QuoteRequest(uuid4(), "NASDAQ", "TEST", "USD"),
                    QuoteRequest(uuid4(), "SSE", "600519", "USD"),
                ),
                as_of=NOW,
            )
            == {}
        )
