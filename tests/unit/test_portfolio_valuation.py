"""MVP-202 deterministic reference amounts and explicit incomplete sizing context."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from investment_os.application.market_data import (
    MarketDataSnapshot,
    MarketQuote,
    QuoteProvenance,
    unavailable,
)
from investment_os.application.portfolio_valuation import (
    FrozenHolding,
    FrozenPolicy,
    FrozenPortfolio,
    PortfolioValuationService,
)
from investment_os.domain.errors import DomainError
from investment_os.domain.valuation import HoldingInput, value_portfolio

A, B = UUID(int=1), UUID(int=2)
NOW = datetime(2026, 10, 27, tzinfo=UTC)


def holding(instrument=A, **changes):
    return replace(
        HoldingInput(instrument, "CNY", "合成行业", Decimal("10"), Decimal("2"), Decimal("15.25")),
        **changes,
    )


def test_exact_nav_bucket_values_weights_and_sector_exposure_reconcile():
    result = value_portfolio(
        "CNY",
        Decimal("17"),
        (
            holding(),
            holding(
                B,
                core_quantity=Decimal("1"),
                tactical_quantity=Decimal("0"),
                sector="另一行业",
                reference_price=Decimal("10"),
            ),
        ),
    )
    assert result.nav == Decimal("210")
    assert result.market_value == Decimal("193")
    row = result.holdings[0]
    assert (row.core_value, row.tactical_value, row.total_value) == (
        Decimal("152.50"),
        Decimal("30.50"),
        Decimal("183"),
    )
    with localcontext() as ctx:
        ctx.prec = 80
        assert row.total_weight == Decimal("183") / Decimal("210")
        assert result.gross_exposure == Decimal("193") / Decimal("210")
        assert result.net_exposure == result.gross_exposure
        assert dict(result.sector_weights)["合成行业"] == row.total_weight


def test_missing_price_never_shows_partial_sum_as_nav_or_any_weight():
    result = value_portfolio("CNY", Decimal("100"), (holding(), holding(B, reference_price=None)))
    assert result.status == "MISSING_PRICES"
    assert result.nav is result.market_value is result.gross_exposure is None
    assert all(row.total_weight is None for row in result.holdings)
    assert result.holdings[0].total_value == Decimal("183")
    assert result.holdings[1].total_value is None


@pytest.mark.parametrize("base,currency", [("USD", "CNY"), ("CNY", "HKD")])
def test_foreign_currency_never_uses_one_to_one_fx(base, currency):
    result = value_portfolio(base, Decimal("100"), (holding(currency=currency),))
    assert result.status == "FX_REQUIRED"
    assert result.nav is result.holdings[0].total_value is None


def test_cash_only_zero_nav_and_zero_position_do_not_invent_prices_or_ratios():
    assert value_portfolio("CNY", Decimal("12.5"), ()).cash_weight == Decimal(1)
    result = value_portfolio(
        "CNY",
        Decimal(0),
        (holding(core_quantity=Decimal(0), tactical_quantity=Decimal(0), reference_price=None),),
    )
    assert result.nav == 0 and result.status == "ZERO_NAV"
    assert result.cash_weight is result.holdings[0].total_weight is None
    assert result.holdings[0].total_value == 0


@pytest.mark.parametrize(
    "value",
    [
        1.2,
        True,
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-1"),
        Decimal("1e50"),
        Decimal("1e-19"),
    ],
)
def test_financial_inputs_reject_float_nonfinite_negative_and_unsupported_precision(value):
    with pytest.raises((ValueError, DomainError)):
        value_portfolio("CNY", value, ())


def test_duplicate_holdings_and_excessive_count_fail_closed():
    with pytest.raises(ValueError, match="HOLDINGS_INVALID"):
        value_portfolio("CNY", Decimal(0), (holding(), holding()))
    with pytest.raises(ValueError, match="HOLDINGS_INVALID"):
        value_portfolio("CNY", Decimal(0), tuple(holding(UUID(int=i + 1)) for i in range(1001)))


@given(
    cash=st.integers(0, 100000),
    core=st.integers(0, 10000),
    tactical=st.integers(0, 10000),
    price=st.integers(1, 100000),
)
def test_reference_valuation_is_order_independent_and_reconciles_without_float(
    cash, core, tactical, price
):
    first = holding(
        core_quantity=Decimal(core),
        tactical_quantity=Decimal(tactical),
        reference_price=Decimal(price),
    )
    second = holding(B)
    result = value_portfolio("CNY", Decimal(cash), (first, second))
    assert result == value_portfolio("CNY", Decimal(cash), (second, first))
    assert result.nav == Decimal(cash) + Decimal(core + tactical) * Decimal(price) + Decimal("183")
    assert all(row.core_value + row.tactical_value == row.total_value for row in result.holdings)


def book():
    return FrozenPortfolio(
        portfolio_id=uuid4(),
        name="合成组合",
        base_currency="CNY",
        cash="100",
        captured_at=NOW,
        holdings=(
            FrozenHolding(
                position_id=uuid4(),
                instrument_id=A,
                version=1,
                market="SSE",
                symbol="629202",
                name="合成标的",
                currency="CNY",
                sector="合成行业",
                lot_size="100",
                core_quantity="10",
                tactical_quantity="2",
                core_average_cost="11",
                tactical_average_cost="12",
            ),
        ),
        policy=FrozenPolicy(status="MISSING", reason_code="POLICY_MISSING"),
    )


class Inputs:
    def __init__(self, value):
        self.value = value

    async def capture(self, _):
        return self.value


class Quotes:
    def __init__(self, status="AVAILABLE", mutate=None):
        self.status = status
        self.requests = []
        self.mutate = mutate

    async def get_snapshot(self, request):
        self.requests.append(request)
        if self.status != "AVAILABLE":
            return unavailable(request, self.status, self.status)
        provenance = QuoteProvenance(
            instrument_id=A,
            evidence_id=UUID(int=3),
            content_hash="a" * 64,
            source_name=request.source_name,
            source_locator="synthetic://quote",
            currency="CNY",
            observed_at=NOW - timedelta(hours=1),
            effective_at=NOW - timedelta(hours=1),
            available_at=NOW - timedelta(minutes=30),
            ingested_at=NOW - timedelta(minutes=20),
            expires_at=NOW + timedelta(hours=1),
        )
        result = MarketDataSnapshot(
            **request.model_dump(exclude={"portfolio_id"}),
            status="AVAILABLE",
            reason_code="MANUAL_REFERENCE_ONLY",
            quote=MarketQuote(price="15.25", provenance=provenance),
            provenance=provenance,
        )
        return self.mutate(result) if self.mutate else result


async def test_same_frozen_inputs_and_formula_reproduce_hash_and_decimal_context_but_never_sizing():
    snapshot = book()
    market = Quotes()
    service = PortfolioValuationService(Inputs(snapshot), market)
    a = await service.get_context(
        snapshot.portfolio_id, source="MANUAL_MARKET", source_name="合成来源"
    )
    b = await service.get_context(
        snapshot.portfolio_id, source="MANUAL_MARKET", source_name="合成来源"
    )
    assert a == b and a.input_hash == b.input_hash and a.output_hash == b.output_hash
    assert a.nav == Decimal("283")
    assert a.sizing_ready is a.trading_grade is a.auto_trade is False
    assert a.instrument_volatility is a.liquidity_capacity is a.pending_capacity is None
    assert {
        "POLICY_MISSING",
        "MANUAL_REFERENCE_NOT_TRADING_GRADE",
        "HISTORICAL_VOLATILITY_UNAVAILABLE",
        "PENDING_CAPACITY_UNAVAILABLE",
    } <= set(a.blockers)
    assert a.quotes[0].provenance.trading_grade is False
    assert market.requests[0].as_of == snapshot.captured_at
    updated = snapshot.model_copy(update={"cash": Decimal("101")})
    changed = await PortfolioValuationService(Inputs(updated), Quotes()).get_context(
        snapshot.portfolio_id, source="MANUAL_MARKET", source_name="合成来源"
    )
    assert changed.input_hash != a.input_hash


@pytest.mark.parametrize(
    "status", ["MISSING", "EXPIRED", "NOT_YET_AVAILABLE", "INVALID", "UNSUPPORTED_SOURCE"]
)
async def test_quote_failure_is_visible_and_never_falls_back(status):
    snapshot = book()
    market = Quotes(status)
    result = await PortfolioValuationService(Inputs(snapshot), market).get_context(
        snapshot.portfolio_id, source="MANUAL_MARKET", source_name="合成来源"
    )
    assert result.nav is None and f"QUOTE_{status}" in result.blockers
    assert len(market.requests) == 1


@pytest.mark.parametrize("kind", ["target", "time"])
async def test_mismatched_or_future_response_is_rejected_even_from_typed_port(kind):
    snapshot = book()

    def mutate(result):
        if kind == "target":
            return result.model_copy(update={"instrument_id": B})
        provenance = result.provenance.model_copy(
            update={"ingested_at": NOW + timedelta(seconds=1)}
        )
        return result.model_copy(
            update={
                "provenance": provenance,
                "quote": result.quote.model_copy(update={"provenance": provenance}),
            }
        )

    with pytest.raises(ValueError, match="VALUATION_QUOTE"):
        await PortfolioValuationService(Inputs(snapshot), Quotes(mutate=mutate)).get_context(
            snapshot.portfolio_id, source="MANUAL_MARKET", source_name="合成来源"
        )


async def test_fx_boundary_does_not_even_query_reference_price():
    snapshot = book().model_copy(update={"base_currency": "USD"})
    market = Quotes()
    result = await PortfolioValuationService(Inputs(snapshot), market).get_context(
        snapshot.portfolio_id, source="MANUAL_MARKET", source_name="合成来源"
    )
    assert result.nav is None and "FX_REQUIRED" in result.blockers and not market.requests


async def test_http_valuation_route_is_typed_read_only_and_never_probes_on_manifest(monkeypatch):
    import httpx

    from investment_os.api.app import create_app

    snapshot = book()
    service = PortfolioValuationService(Inputs(snapshot), Quotes())
    app = create_app(valuation_service=service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        path = f"/api/v1/valuation/portfolios/{snapshot.portfolio_id}"
        result = await client.get(
            path, params={"source": "MANUAL_MARKET", "source_name": "合成来源"}
        )
        assert result.status_code == 200
        assert result.json()["nav"] == "283.00" and result.json()["sizing_ready"] is False
        assert (await client.get(path)).status_code == 422
        manifest = (await client.get("/api/v1/product-acceptance")).json()
        item = next(i for i in manifest["capabilities"] if i["key"] == "valuation")
        assert item["route"] == "/valuation" and item["human_acceptance"] == "PENDING"
        assert (await client.post(path)).status_code == 405
    app_unavailable = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_unavailable), base_url="http://test"
    ) as client:
        assert (
            await client.get(path, params={"source": "MANUAL_MARKET", "source_name": "合成来源"})
        ).status_code == 503
