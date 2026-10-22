"""冻结估值的精确、失败与边界验证, 不涉及真实资金或来源。"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal, Inexact, localcontext
from uuid import UUID, uuid4

import pytest

from investment_os.application.analysis_valuation import build_analysis_valuation
from investment_os.application.market_data import MarketQuote
from investment_os.application.portfolio_book import PortfolioPositionView, PortfolioView

NOW = datetime(2026, 10, 22, 7, tzinfo=UTC)
A, B = UUID(int=1), UUID(int=2)


def position(identity=A, core="2", tactical="1", sector="合成行业", currency="CNY"):
    return PortfolioPositionView(
        uuid4(),
        identity,
        "SSE",
        str(identity.int),
        "合成标的",
        "EQUITY",
        currency,
        sector,
        Decimal(core),
        Decimal(tactical),
        Decimal("1"),
    )


def portfolio(*positions, cash="100"):
    return PortfolioView(UUID(int=3), "合成组合", "CNY", Decimal(cash), "ACTIVE", positions)


def quote(identity=A, price="10", currency="CNY"):
    return MarketQuote(identity, Decimal(price), currency, NOW, "合成报价")


def calculate(book=None, quotes=None, **kwargs):
    return build_analysis_valuation(
        portfolio=book or portfolio(position()),
        target_id=A,
        target_currency="CNY",
        as_of=NOW,
        quotes=quotes if quotes is not None else {A: quote()},
        **kwargs,
    )


def test_exact_core_tactical_nav_weights_and_manual_sector_provenance():
    result = calculate(
        portfolio(position(), position(B, core="4", tactical="0", sector="")),
        {A: quote(), B: quote(B, "5")},
    )
    assert result.status == "OK"
    assert result.status == "OK" and result.nav == Decimal("150")
    assert result.holdings_value == Decimal("50")
    assert result.cash_balance + result.holdings_value == result.nav
    first = result.position_values[0]
    assert first.core_value == Decimal("20") and first.tactical_value == Decimal("10")
    assert first.market_value == first.core_value + first.tactical_value
    with localcontext() as context:
        context.prec = 128
        assert first.weight == first.core_weight + first.tactical_weight
        assert result.gross_exposure == Decimal("50") / Decimal("150")
    assert result.target_weight == first.weight
    assert result.unclassified_value == Decimal("20")
    assert result.sector_values[0].market_value == Decimal("30")
    assert result.sector_values[0].classification_source == "PORTFOLIO_INPUT"
    assert result.price_availability == "PROVIDER_TIME_ONLY"


def test_hash_and_decimal_results_ignore_order_and_callers_precision():
    book = portfolio(position(), position(B, "0.123456789", "0.987654321"))
    quotes = {A: quote(price="12.345678901"), B: quote(B, "1.111111119")}
    first = calculate(book, quotes)
    with localcontext() as context:
        context.prec = 6
        context.rounding = ROUND_FLOOR
        context.traps[Inexact] = True
        second = calculate(
            replace(book, positions=book.positions[::-1]), dict(reversed(list(quotes.items())))
        )
    assert first == second
    changed = calculate(replace(book, cash_balance=Decimal("101")), quotes)
    assert changed.input_hash != first.input_hash
    assert "E-" not in first.model_dump_json()


def test_missing_held_price_keeps_known_rows_but_nav_and_weights_unknown():
    result = calculate(portfolio(position(), position(B)), {A: quote()})
    assert result.status == "PARTIAL" and result.nav is None
    assert result.missing_quotes == (B,)
    assert result.position_values[0].core_value == Decimal("20")
    assert result.position_values[1].market_value is None
    assert all(r.weight is None for r in result.position_values)
    assert result.unclassified_value is None


def test_target_missing_does_not_destroy_known_nav_or_invent_target_price():
    result = calculate(portfolio(position(B)), {B: quote(B)})
    assert result.status == "PARTIAL" and result.nav == Decimal("130")
    assert result.target_reference_price is None and result.target_weight == 0


def test_zero_holding_needs_no_price_but_empty_cash_has_no_valid_weight():
    result = calculate(portfolio(position(B, "0", "0")), {A: quote()})
    assert result.status == "OK" and result.nav == 100
    assert result.position_values[0].price is None
    assert result.position_values[0].market_value == 0
    empty = calculate(portfolio(cash="0"), {A: quote()})
    assert empty.status == "FAILED" and empty.nav == 0
    assert empty.target_weight is None and "NAV_NON_POSITIVE" in empty.reason_codes


@pytest.mark.parametrize("target_foreign", [True, False])
def test_foreign_watch_target_or_held_currency_requires_real_fx(target_foreign):
    result = build_analysis_valuation(
        portfolio=portfolio() if target_foreign else portfolio(position(B, currency="USD")),
        target_id=A,
        target_currency="USD" if target_foreign else "CNY",
        as_of=NOW,
        quotes={A: quote(currency="USD" if target_foreign else "CNY"), B: quote(B, currency="USD")}
        if not target_foreign
        else {A: quote(currency="USD")},
    )
    assert result.status == "FAILED" and result.nav is None
    assert "FX_SOURCE_MISSING_MULTI_CURRENCY" in result.reason_codes
    assert result.target_weight is None


@pytest.mark.parametrize(
    "change",
    [
        {"as_of": NOW + timedelta(seconds=1)},
        {"as_of": NOW.replace(tzinfo=None)},
        {"instrument_id": B},
        {"currency": "USD"},
        {"reference_price": Decimal("0")},
        {"reference_price": Decimal("-1")},
        {"reference_price": Decimal("NaN")},
        {"reference_price": 1.1},
        {"source": ""},
        {"source_rank": -1},
    ],
)
def test_invalid_quote_fails_closed_without_zero_nav_or_quantity(change):
    result = calculate(quotes={A: replace(quote(), **change)})
    assert result.status == "FAILED" and result.nav is None
    assert result.target_reference_price is None
    assert "INVALID_REFERENCE_QUOTES" in result.reason_codes


def test_duplicate_holding_or_negative_cash_is_not_silently_clamped():
    for book in (portfolio(position(), position()), portfolio(position(), cash="-1")):
        result = calculate(book)
        assert result.status == "FAILED" and result.nav is None
        assert "VALUATION_INPUT_INVALID" in result.reason_codes


def test_decimal_zero_serializes_without_exponent_and_degraded_source_is_preserved():
    result = calculate(
        portfolio(position(core="0.0000000000", tactical="1")),
        {A: replace(quote(), degraded=True, source_rank=1)},
    )
    encoded = result.model_dump(mode="json")
    assert encoded["position_values"][0]["core_quantity"] == "0.0000000000"
    assert result.degraded and result.degraded_instruments == (A,)
