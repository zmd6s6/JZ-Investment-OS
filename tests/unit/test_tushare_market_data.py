"""Tushare official envelope parsing, numeric close prices, and disable-profile freshness."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from investment_os.application.market_data import MarketDataSourceFailure, QuoteRequest
from investment_os.infrastructure.tushare.market_data import TushareMarketDataAdapter


class _FakeAsyncClient:
    def __init__(self, raw_text: str):
        self._raw_text = raw_text

    async def post(self, url: str, json=None):
        class _Resp:
            def __init__(self, text: str):
                self._text = text

            def raise_for_status(self):
                return None

            @property
            def text(self):
                return self._text

            def json(self):
                import json as _json

                return _json.loads(self._text)

        return _Resp(self._raw_text)

    async def aclose(self):
        return None


async def test_tushare_parses_numeric_close_as_decimal() -> None:
    import json

    now = datetime(2026, 10, 10, tzinfo=UTC)
    instrument_id = uuid4()
    trade = "20261009"
    # Official style: close is a JSON number, not a string.
    payload = {
        "code": 0,
        "msg": "获取成功",
        "data": {
            "fields": ["ts_code", "trade_date", "close"],
            "items": [["600519.SH", trade, 1500.5]],
        },
    }
    raw = json.dumps(payload, ensure_ascii=False)
    adapter = TushareMarketDataAdapter(
        token="synthetic-token",
        client=_FakeAsyncClient(raw),  # type: ignore[arg-type]
    )
    quotes = await adapter.get_quotes(
        (
            QuoteRequest(
                instrument_id=instrument_id,
                market="SSE",
                symbol="600519",
                expected_currency="CNY",
            ),
        ),
        as_of=now,
    )
    assert instrument_id in quotes
    assert quotes[instrument_id].reference_price == Decimal("1500.5")
    assert isinstance(quotes[instrument_id].reference_price, Decimal)
    assert quotes[instrument_id].volatility is None


async def test_tushare_parses_official_data_fields_items_envelope() -> None:
    import json

    now = datetime(2026, 10, 10, tzinfo=UTC)
    instrument_id = uuid4()
    trade = "20261009"
    payload = {
        "code": 0,
        "msg": "获取成功",
        "data": {
            "fields": ["ts_code", "trade_date", "close"],
            "items": [["600519.SH", trade, "1500.5"]],
        },
    }
    adapter = TushareMarketDataAdapter(
        token="synthetic-token",
        client=_FakeAsyncClient(json.dumps(payload)),  # type: ignore[arg-type]
    )
    quotes = await adapter.get_quotes(
        (
            QuoteRequest(
                instrument_id=instrument_id,
                market="SSE",
                symbol="600519",
                expected_currency="CNY",
            ),
        ),
        as_of=now,
    )
    assert instrument_id in quotes
    assert quotes[instrument_id].reference_price == Decimal("1500.5")
    assert quotes[instrument_id].source == "TUSHARE"


async def test_daily_fields_use_one_same_day_request_and_exact_standard_units():
    import json

    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["params"] == {"trade_date": "20261009"}
        assert set(payload["fields"].split(",")) == {
            "ts_code",
            "trade_date",
            "close",
            "open",
            "high",
            "low",
            "pre_close",
            "vol",
            "amount",
        }
        return httpx.Response(
            200,
            text='{"code":0,"data":{"fields":["ts_code","trade_date","close","open","high","low","pre_close","vol","amount"],"items":[["600519.SH","20261009",11.5,10,12,9,10,123.45,141.9675]]}}',
        )

    identity = uuid4()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await TushareMarketDataAdapter(token="synthetic-only", client=client).get_quotes(
            (QuoteRequest(identity, "SSE", "600519"),), as_of=datetime(2026, 10, 9, 8, tzinfo=UTC)
        )
    assert len(requests) == 1
    value = result[identity]
    assert value.volatility is None
    assert value.daily_bar.volume_shares == Decimal("12345")
    assert value.daily_bar.turnover == Decimal("141967.5")
    assert value.daily_bar.previous_close_basis == "EX_RIGHTS"
    assert value.daily_bar.close == value.reference_price
    assert value.daily_bar.as_of == value.as_of


@pytest.mark.parametrize("extra", [{"vol": -1}, {"amount": "NaN"}, {"high": 9}, {"pre_close": 0}])
async def test_invalid_optional_daily_data_rejects_the_source_not_silent_field_removal(extra):
    import json

    fields = ["ts_code", "trade_date", "close", *extra]
    raw = json.dumps(
        {
            "code": 0,
            "data": {"fields": fields, "items": [["600519.SH", "20261009", "11", *extra.values()]]},
        }
    )
    adapter = TushareMarketDataAdapter(token="synthetic-only", client=_FakeAsyncClient(raw))
    with pytest.raises(MarketDataSourceFailure, match="daily fields invalid"):
        await adapter.get_quotes(
            (QuoteRequest(uuid4(), "SSE", "600519"),), as_of=datetime(2026, 10, 9, 8, tzinfo=UTC)
        )


async def test_missing_daily_fields_keep_legacy_quote_without_fabricated_metrics():
    import json

    raw = json.dumps(
        {
            "code": 0,
            "data": {
                "fields": ["ts_code", "trade_date", "close"],
                "items": [["600519.SH", "20261009", "11"]],
            },
        }
    )
    identity = uuid4()
    adapter = TushareMarketDataAdapter(token="synthetic-only", client=_FakeAsyncClient(raw))
    quotes = await adapter.get_quotes(
        (QuoteRequest(identity, "SSE", "600519"),), as_of=datetime(2026, 10, 9, 8, tzinfo=UTC)
    )
    assert quotes[identity].daily_bar is None
