"""Tushare official envelope parsing, numeric close prices, and disable-profile freshness."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from investment_os.application.market_data import QuoteRequest
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
