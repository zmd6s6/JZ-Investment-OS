"""MVP-201 exact inputs and typed service fail-closed boundary."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from investment_os.api.market_routes import market_router
from investment_os.application.evidence import normalize_artifact
from investment_os.application.market_data import (
    ManualQuoteInput,
    MarketDataError,
    MarketDataRequest,
    MarketDataService,
    unavailable,
)
from investment_os.infrastructure.manual_market_data import quote_artifact

NOW = datetime(2026, 10, 27, 0, tzinfo=UTC)


def command(**changes):
    values = dict(
        request_id=uuid4(),
        instrument_id=uuid4(),
        source_name="合成公开资料",
        source_locator="synthetic://quote",
        currency="CNY",
        price="1500.500000000000000001",
        observed_at=NOW - timedelta(hours=1),
        effective_at=NOW - timedelta(hours=1),
        available_at=NOW - timedelta(minutes=30),
        expires_at=NOW + timedelta(days=1),
    )
    return ManualQuoteInput.model_validate(values | changes)


@pytest.mark.parametrize(
    "price", [1500.5, True, "NaN", "Infinity", "0", "-1", "1e2", "1,000", "0.0000000000000000001"]
)
def test_manual_quote_rejects_non_exact_or_non_positive_price(price):
    with pytest.raises(ValidationError):
        command(price=price)


@pytest.mark.parametrize(
    "changes",
    [
        dict(observed_at=NOW.replace(tzinfo=None)),
        dict(available_at=NOW - timedelta(days=1)),
        dict(expires_at=NOW - timedelta(minutes=30)),
        dict(source_name="   "),
        dict(extra="forbidden"),
    ],
)
def test_manual_quote_rejects_invalid_times_or_identity(changes):
    with pytest.raises(ValidationError):
        command(**changes)


def test_full_quote_hash_binds_instrument_and_expiry_without_changing_legacy_evidence():
    original = command()

    def digest(c):
        return normalize_artifact(quote_artifact(c), ingested_at=NOW).content_hash

    assert digest(original) == digest(original.model_copy(update={"request_id": uuid4()}))
    assert digest(original) != digest(original.model_copy(update={"instrument_id": uuid4()}))
    assert digest(original) != digest(
        original.model_copy(update={"expires_at": NOW + timedelta(days=2)})
    )
    assert original.price == "1500.500000000000000001"


def service(currency="CNY", portfolio=None):
    port = AsyncMock()
    port.get_snapshot.side_effect = lambda r: unavailable(r, "MISSING", "SYNTHETIC_MISSING")
    catalog = AsyncMock()
    catalog.get.return_value = SimpleNamespace(currency=currency)
    books = AsyncMock()
    books.get_portfolio.return_value = portfolio
    result = MarketDataService({"MANUAL_MARKET": port}, port, catalog, books, now=lambda: NOW)
    return result, port


@pytest.mark.parametrize(
    "changes, status",
    [
        ({"as_of": NOW + timedelta(seconds=1)}, "NOT_YET_AVAILABLE"),
        ({"base_currency": "USD"}, "FX_REQUIRED"),
        ({"source": "BOCHA"}, "UNSUPPORTED_SOURCE"),
    ],
)
async def test_future_fx_and_unknown_source_never_call_provider(changes, status):
    app, port = service()
    req = MarketDataRequest(
        instrument_id=uuid4(), source="MANUAL_MARKET", source_name="x", as_of=NOW
    )
    result = await app.get_snapshot(req.model_copy(update=changes))
    assert result.status == status and result.quote is None
    port.get_snapshot.assert_not_awaited()


async def test_non_cny_instrument_and_mixed_portfolio_fail_closed():
    req = MarketDataRequest(
        instrument_id=uuid4(), source="MANUAL_MARKET", source_name="x", as_of=NOW
    )
    app, port = service(currency="USD")
    assert (await app.get_snapshot(req)).status == "FX_REQUIRED"
    port.get_snapshot.assert_not_awaited()
    mixed = SimpleNamespace(
        base_currency="CNY",
        positions=[
            SimpleNamespace(
                currency="USD", core_quantity=Decimal("1"), tactical_quantity=Decimal("0")
            )
        ],
    )
    app, port = service(portfolio=mixed)
    assert (
        await app.get_snapshot(req.model_copy(update={"portfolio_id": uuid4()}))
    ).status == "FX_REQUIRED"
    port.get_snapshot.assert_not_awaited()


async def test_port_envelope_mismatch_is_rejected_without_fallback():
    app, port = service()
    req = MarketDataRequest(
        instrument_id=uuid4(), source="MANUAL_MARKET", source_name="x", as_of=NOW
    )
    port.get_snapshot.side_effect = None
    port.get_snapshot.return_value = unavailable(
        req.model_copy(update={"instrument_id": uuid4()}), "MISSING", "x"
    )
    with pytest.raises(MarketDataError, match="MARKET_RESPONSE_MISMATCH"):
        await app.get_snapshot(req)
    assert port.get_snapshot.await_count == 1


async def test_unwired_capability_and_blank_query_have_safe_http_errors():
    app = FastAPI()
    app.include_router(market_router(None))
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        assert (await client.get("/api/v1/market-data/capabilities")).json()[
            "status"
        ] == "UNAVAILABLE"
        response = await client.get(
            "/api/v1/market-data/reference-quote",
            params={"instrument_id": str(uuid4()), "source_name": " "},
        )
        assert response.status_code == 422
        response = await client.post(
            "/api/v1/market-data/manual-quotes", json=command().model_dump(mode="json")
        )
        assert response.status_code == 503


async def test_manual_route_auth_validation_and_exact_response():
    from investment_os.api.app import create_app
    from investment_os.application.market_data import ManualQuoteSaved

    app_service, port = service()
    item = command()
    port.save_quote.return_value = ManualQuoteSaved(
        request_id=item.request_id, evidence_id=uuid4(), content_hash="a" * 64, ingested_at=NOW
    )
    app = create_app(market_data_service=app_service, write_api_token="synthetic-manual-api")
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        body = item.model_dump(mode="json")
        assert (
            await client.post("/api/v1/market-data/manual-quotes", json=body)
        ).status_code == 401
        headers = {"Authorization": "Bearer synthetic-manual-api"}
        response = await client.post(
            "/api/v1/market-data/manual-quotes", json=body, headers=headers
        )
        assert response.status_code == 200
        assert response.json()["evidence_id"] == str(port.save_quote.return_value.evidence_id)
        bad = await client.post(
            "/api/v1/market-data/manual-quotes", json=body | {"price": 15.25}, headers=headers
        )
        assert bad.status_code == 422
        port.save_quote.assert_awaited_once()


async def test_typed_port_cannot_claim_future_or_expired_quote_available():
    from investment_os.application.market_data import (
        MarketDataSnapshot,
        MarketQuote,
        QuoteProvenance,
    )

    app, port = service()
    port.get_snapshot.side_effect = None
    req = MarketDataRequest(
        instrument_id=uuid4(), source="MANUAL_MARKET", source_name="x", as_of=NOW
    )
    for expiry, ingested in [(NOW, NOW), (NOW + timedelta(days=1), NOW + timedelta(seconds=1))]:
        provenance = QuoteProvenance(
            instrument_id=req.instrument_id,
            evidence_id=uuid4(),
            content_hash="a" * 64,
            source_name="x",
            source_locator="synthetic://manual",
            currency="CNY",
            observed_at=NOW,
            effective_at=NOW,
            available_at=NOW,
            ingested_at=ingested,
            expires_at=expiry,
        )
        port.get_snapshot.return_value = MarketDataSnapshot(
            **req.model_dump(exclude={"portfolio_id"}),
            status="AVAILABLE",
            reason_code="synthetic",
            quote=MarketQuote(price=Decimal("1"), provenance=provenance),
            provenance=provenance,
        )
        with pytest.raises(MarketDataError, match="MARKET_RESPONSE_TIME_INVALID"):
            await app.get_snapshot(req)


@pytest.mark.parametrize("assembled", [False, True])
def test_manual_market_manifest_never_accepts_owner_checkpoint(assembled):
    from investment_os.application.acceptance import acceptance_snapshot

    snapshot = acceptance_snapshot(
        portfolio=False, watchlist=False, providers=False, policy=False, market_data=assembled
    )
    item = next(item for item in snapshot.capabilities if item.key == "market_data")
    assert item.route == ("/market-data" if assembled else None)
    assert item.service == ("ASSEMBLED" if assembled else "UNAVAILABLE")
    assert item.human_acceptance == "PENDING"
    assert "未经独立核实" in item.detail
