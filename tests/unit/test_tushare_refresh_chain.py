"""Refreshable Tushare chain stops using Tushare after profile disable."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from investment_os.application.market_data import InMemoryMarketDataAdapter, QuoteRequest
from investment_os.infrastructure.tushare.market_data import (
    TUSHARE_PROVIDER_TYPE,
    RefreshableTushareChain,
    TushareMarketDataAdapter,
)


class _ProfileStore:
    def __init__(self) -> None:
        self.enabled = True

    async def list_profiles(self):
        return [
            SimpleNamespace(
                name="tushare-main",
                enabled=self.enabled,
                provider_type=TUSHARE_PROVIDER_TYPE,
                credential_ref=uuid4(),
                id=uuid4(),
            )
        ]

    async def get_credential(self, ref):
        return "token"


async def test_disable_profile_stops_tushare_source() -> None:
    store = _ProfileStore()
    chain = RefreshableTushareChain(
        list_profiles=store.list_profiles,
        get_credential=store.get_credential,
    )
    await chain._refresh_sources()
    names = [s.name for s in chain._chain._sources]
    assert "TUSHARE" in names

    store.enabled = False
    await chain._refresh_sources()
    names_after = [s.name for s in chain._chain._sources]
    assert "TUSHARE" not in names_after
    assert names_after[-1] == InMemoryMarketDataAdapter.name


async def test_numeric_json_close_parses_via_adapter_client() -> None:
    import json

    payload = {
        "code": 0,
        "msg": "ok",
        "data": {
            "fields": ["ts_code", "trade_date", "close"],
            "items": [["600519.SH", "20261009", 1500.5]],
        },
    }
    raw = json.dumps(payload)
    adapter = TushareMarketDataAdapter(token="t", client=_TextClient(raw))  # type: ignore[arg-type]
    quotes = await adapter.get_quotes(
        (
            QuoteRequest(
                instrument_id=uuid4(),
                market="SSE",
                symbol="600519",
                expected_currency="CNY",
            ),
        ),
        as_of=datetime(2026, 10, 10, tzinfo=UTC),
    )
    assert len(quotes) == 1
    assert next(iter(quotes.values())).reference_price == Decimal("1500.5")


class _TextClient:
    def __init__(self, text: str):
        self._text = text

    async def post(self, url, json=None):
        text = self._text

        class _Resp:
            def raise_for_status(self):
                return None

            @property
            def text(self):
                return text

            def json(self):
                import json as _json

                return _json.loads(text)

        return _Resp()

    async def aclose(self):
        return None
