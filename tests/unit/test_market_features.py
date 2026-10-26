"""单日观察不是波动率或仓位容量; 全部使用合成输入。"""

from datetime import timedelta
from decimal import ROUND_FLOOR, Decimal, Inexact, localcontext

import pytest
from pydantic import ValidationError
from test_analysis_valuation import NOW, A, calculate, portfolio, quote

from investment_os.application.analysis_execution_context import execution_input_hash
from investment_os.application.analysis_models import digest
from investment_os.application.analysis_valuation import AnalysisValuation
from investment_os.application.market_features import DailyMarketBar, build_daily_features
from investment_os.domain.errors import DomainError


def bar(**changes):
    return DailyMarketBar(
        **{
            "instrument_id": A,
            "as_of": NOW,
            "close": "11",
            "open": "10",
            "high": "12",
            "low": "9",
            "previous_close": "10",
            "volume_shares": "12345",
            "turnover": "129000.125",
            **changes,
        }
    )


def features(value):
    return build_daily_features(
        value, currency="CNY", source="合成次源", source_rank=1, degraded=True
    )


def test_exact_daily_return_range_provenance_and_not_sizing_capacity():
    result = features(bar())
    assert result.daily_return == Decimal("0.1")
    assert result.intraday_range == Decimal("0.3")
    assert result.volume_shares == Decimal("12345")
    assert result.turnover == Decimal("129000.125")
    assert result.status == "OK" and not result.missing_fields
    assert result.source == "合成次源" and result.source_rank == 1 and result.degraded
    assert result.sizing_ready is False and result.availability == "PROVIDER_TIME_ONLY"
    assert "volatility" not in result.model_dump(mode="json")


def test_missing_values_stay_unknown_but_true_zero_volume_is_preserved():
    result = features(bar(previous_close=None, high=None, volume_shares="0", turnover="0"))
    assert result.status == "PARTIAL"
    assert result.daily_return is None and result.intraday_range is None
    assert result.volume_shares == result.turnover == 0
    assert set(result.missing_fields) == {"previous_close", "high"}


@pytest.mark.parametrize(
    "changes",
    [
        {"close": 1.5},
        {"close": True},
        {"turnover": "NaN"},
        {"open": "Infinity"},
        {"previous_close": "0"},
        {"volume_shares": "-1"},
        {"turnover": "-1"},
        {"high": "10"},
        {"low": "12"},
        {"as_of": NOW.replace(tzinfo=None)},
    ],
)
def test_invalid_daily_values_do_not_become_trusted_observations(changes):
    with pytest.raises((ValidationError, DomainError)):
        bar(**changes)


def test_daily_calculation_and_hash_ignore_callers_decimal_context():
    value = bar(close="10.123456789123456789", previous_close="3")
    expected = features(value)
    with localcontext() as context:
        context.prec = 5
        context.rounding = ROUND_FLOOR
        context.traps[Inexact] = True
        assert features(value) == expected
    assert features(bar(turnover="129000.126")).input_hash != features(bar()).input_hash
    assert features(bar(previous_close_basis="EX_RIGHTS")).input_hash != features(bar()).input_hash


def test_model_copy_cannot_smuggle_a_float_into_daily_calculation():
    with pytest.raises(DomainError):
        features(bar().model_copy(update={"close": 10.5}))


def test_daily_inputs_change_valuation_and_runtime_hash_but_not_nav():
    from dataclasses import replace

    first_quote = replace(quote(price="11"), daily_bar=bar())
    first = calculate(quotes={A: first_quote})
    second = calculate(quotes={A: replace(first_quote, daily_bar=bar(volume_shares="54321"))})
    assert first.nav == second.nav
    assert first.input_hash != second.input_hash
    assert execution_input_hash("a" * 64, first) != execution_input_hash("a" * 64, second)
    assert first.target_market_features.bar == bar()
    assert first.target_market_features.source == first.source
    assert first.target_market_features.source_rank == first.source_rank
    assert first.target_market_features.degraded == first.degraded


@pytest.mark.parametrize(
    "change",
    [{"instrument_id": A.__class__(int=5)}, {"as_of": NOW - timedelta(seconds=1)}, {"close": "10"}],
)
def test_daily_identity_time_and_close_must_match_reference_quote(change):
    from dataclasses import replace

    result = calculate(quotes={A: replace(quote(price="11"), daily_bar=bar(**change))})
    assert result.status == "FAILED"
    assert "INVALID_REFERENCE_QUOTES" in result.reason_codes
    assert result.target_market_features is None


def test_historical_valuation_json_and_hash_are_byte_compatible_without_daily_extension():
    value = calculate(portfolio())
    raw = value.model_dump(mode="json")
    assert "target_market_features" not in raw
    restored = AnalysisValuation.model_validate_json(value.model_dump_json())
    assert restored.model_dump(mode="json") == raw
    assert execution_input_hash("a" * 64, restored) == digest(
        {
            "schema_version": "1.0",
            "feature_set_version": "analysis-portfolio-context-v1",
            "request_input_hash": "a" * 64,
            "valuation": raw,
        }
    )
