"""MockTransport验证显式有界历史请求; 不使用真实Token。"""

import json
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from test_analysis_market import add, configured
from test_analysis_valuation import NOW, A

from investment_os.application.errors import ApplicationError
from investment_os.application.market_data import QuoteRequest
from investment_os.infrastructure.analysis_market import PlannedMarketDataFactory
from investment_os.infrastructure.tushare.market_data import TushareMarketDataAdapter


def row(at=NOW, symbol="600000.SH"):
    return [symbol, at.strftime("%Y%m%d"), 10.5, 10, 11, 9, 10, 1.25, 2.5]


@pytest.mark.parametrize(
    "fault",
    [None, "http", "schema", "foreign", "duplicate", "future", "old", "close", "volume", "empty"],
)
async def test_history_is_explicit_bounded_numeric_and_failure_does_not_discard_quote(fault):
    calls = []

    def handle(request):
        body = json.loads(request.content)
        calls.append(body)
        rows = [row()]
        if "start_date" in body["params"]:
            if fault == "http":
                return httpx.Response(503)
            if fault == "schema":
                return httpx.Response(200, json={"code": 0, "data": {}})
            rows = [row(NOW - timedelta(days=i)) for i in range(20)]
            if fault == "foreign":
                rows[0][0] = "600001.SH"
            if fault == "duplicate":
                rows.append(rows[0])
            if fault == "future":
                rows[0] = row(NOW + timedelta(days=1))
            if fault == "old":
                rows[-1] = row(NOW - timedelta(days=90))
            if fault == "close":
                rows[0][2] = 10.4
            if fault == "volume":
                rows[0][7] = 1.5
            if fault == "empty":
                rows = []
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "fields": [
                        "ts_code",
                        "trade_date",
                        "close",
                        "open",
                        "high",
                        "low",
                        "pre_close",
                        "vol",
                        "amount",
                    ],
                    "items": rows,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = TushareMarketDataAdapter(token="synthetic-history-only", client=client)
        plain = await adapter.get_quotes((QuoteRequest(A, "SSE", "600000"),), as_of=NOW)
        assert plain[A].history is None and len(calls) == 1
        result = await adapter.get_quotes(
            (QuoteRequest(A, "SSE", "600000", include_history=True),), as_of=NOW
        )
        assert result[A].reference_price == Decimal("10.5") and len(calls) == 3
        assert calls[-1]["params"] == {
            "ts_code": "600000.SH",
            "start_date": (NOW - timedelta(days=89)).strftime("%Y%m%d"),
            "end_date": NOW.strftime("%Y%m%d"),
        }
        history = result[A].history
        if fault:
            assert history.status == "UNAVAILABLE" and not history.bars
        else:
            assert history.status == "RECEIVED" and len(history.bars) == 20
            assert history.bars[-1].volume_shares == Decimal("125")
            assert history.bars[-1].turnover == Decimal("2500")
            assert history.bars[0].as_of < history.bars[-1].as_of


async def test_history_requires_sources_and_factory_marks_only_selected_target():
    port, secrets, settings, config = configured()
    one, two = add(port, secrets), add(port, secrets, "未选")
    with pytest.raises(ApplicationError):
        await config.freeze((), None, history_target_id=A)
    plan = await config.freeze((one.id,), None, history_target_id=A)
    seen = []

    class Source:
        name = "SYNTHETIC"

        async def get_quotes(self, batch, *, as_of):
            seen.extend(batch)
            return {}

    reader = PlannedMarketDataFactory(
        settings, secrets, {"TUSHARE_MARKET": lambda *_: Source()}
    ).for_plan(plan, lambda _: None)
    other = uuid4()
    await reader.get_reference_quotes(
        (other, A),
        as_of=NOW,
        instruments={A: ("SSE", "600000", "CNY"), other: ("SSE", "600001", "CNY")},
    )
    assert [q.instrument_id for q in seen if q.include_history] == [A]
    assert plan.profiles[0].profile_id == one.id and two.id not in [
        p.profile_id for p in plan.profiles
    ]


async def test_history_http_failure_keeps_selected_quote_without_calling_backup():
    port, secrets, settings, config = configured()
    one, two = add(port, secrets), add(port, secrets, "备源")
    calls = []

    def handle(request):
        body = json.loads(request.content)
        calls.append(body)
        if "start_date" in body["params"]:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "fields": ["ts_code", "trade_date", "close"],
                    "items": [["600000.SH", NOW.strftime("%Y%m%d"), 10.5]],
                },
            },
        )

    attempts = []
    reader = PlannedMarketDataFactory(
        settings, secrets, transport=httpx.MockTransport(handle)
    ).for_plan(await config.freeze((one.id, two.id), None, history_target_id=A), attempts.append)
    result = await reader.get_reference_quotes(
        (A,), as_of=NOW, instruments={A: ("SSE", "600000", "CNY")}
    )
    assert (
        result[A].reference_price == Decimal("10.5")
        and result[A].history.reason == "REQUEST_FAILED"
    )
    assert len(calls) == 2 and [a.profile_id for a in attempts] == [one.id]


@pytest.mark.parametrize("value", [1, "true", "false", None])
def test_history_confirmation_requires_a_real_boolean(value):
    from pydantic import ValidationError

    from investment_os.api.schemas import StartAnalysisRequest

    with pytest.raises(ValidationError):
        StartAnalysisRequest(instrument_id=A, portfolio_id=uuid4(), include_market_history=value)
