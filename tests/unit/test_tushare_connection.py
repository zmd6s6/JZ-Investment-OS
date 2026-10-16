"""Tushare settings connection tester uses official envelope without secret persistence."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from investment_os.application.provider_settings import DataProviderProfile
from investment_os.infrastructure.tushare.market_data import (
    TUSHARE_PROVIDER_TYPE,
    TushareConnectionTester,
)


class _TextClient:
    def __init__(self, text: str):
        self._text = text

    async def post(self, url, json=None):
        text = self._text

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                import json as _json

                return _json.loads(text)

        return _Resp()

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_tushare_connection_ok() -> None:
    import json

    client = _TextClient(
        json.dumps(
            {
                "code": 0,
                "msg": "ok",
                "data": {"fields": ["exchange", "cal_date"], "items": [["SSE", "20240102"]]},
            }
        )
    )
    tester = TushareConnectionTester(client=client)  # type: ignore[arg-type]
    ok, detail, _latency = await tester.test(credential="token")
    assert ok is True
    assert "trade_cal" in detail


@pytest.mark.asyncio
async def test_tushare_connection_error() -> None:
    import json

    client = _TextClient(json.dumps({"code": 4001, "msg": "token invalid", "data": None}))
    tester = TushareConnectionTester(client=client)  # type: ignore[arg-type]
    ok, detail, _latency = await tester.test(credential="bad")
    assert ok is False
    assert "token invalid" in detail


def test_profile_type_constant() -> None:
    assert TUSHARE_PROVIDER_TYPE == "TUSHARE_MARKET"
    profile = DataProviderProfile(
        id=uuid4(),
        name="t",
        provider_type=TUSHARE_PROVIDER_TYPE,
        base_url="",
        credential_ref=None,
        timeout_seconds=10,
        enabled=True,
    )
    assert profile.provider_type == TUSHARE_PROVIDER_TYPE


def test_dummy_time() -> None:
    assert datetime.now(UTC).tzinfo is not None
