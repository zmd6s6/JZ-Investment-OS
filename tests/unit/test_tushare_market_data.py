"""Tushare official envelope parsing for market quotes."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from investment_os.application.market_data import QuoteRequest
from investment_os.infrastructure.tushare.market_data import TushareMarketDataAdapter


class _FakeAsyncClient:
    def __init__(self, payload: dict):
        self._payload = payload

    async def post(self, url: str, json=None):
        payload = self._payload

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return payload

        return _Resp()

    async def aclose(self):
        return None


async def test_tushare_parses_official_data_fields_items_envelope() -> None:
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
        client=_FakeAsyncClient(payload),  # type: ignore[arg-type]
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
