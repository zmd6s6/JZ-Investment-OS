"""合成观测统计, 不证明回测可得性或交易级风险输入。"""

from dataclasses import replace
from datetime import timedelta
from decimal import Context, Decimal, Inexact, localcontext
from uuid import uuid4

import pytest
from test_analysis_valuation import NOW, A, calculate, quote

from investment_os.application.analysis_jobs import AnalysisJobService
from investment_os.application.analysis_market import AnalysisMarketPlan
from investment_os.application.analysis_product import StartAnalysisInput
from investment_os.application.market_data import ensure_daily_bar
from investment_os.application.market_features import DailyMarketBar
from investment_os.application.market_history import MarketHistory, build_historical_features
from investment_os.domain.errors import DomainError


def history(count=20, **changes):
    bars = tuple(
        DailyMarketBar(
            instrument_id=A,
            as_of=NOW - timedelta(days=count - 1 - i),
            close="10",
            previous_close="10",
            volume_shares=str(100 + i),
            turnover=str(1000 + i),
        )
        for i in range(count)
    )
    return MarketHistory(
        **{"instrument_id": A, "reference_at": NOW, "status": "RECEIVED", "bars": bars, **changes}
    )


def features(value):
    return build_historical_features(
        value, source="合成次源", currency="CNY", source_rank=1, degraded=True
    )


def test_twenty_observations_exact_zero_return_and_mean_with_provenance():
    value = features(history())
    assert value.daily_return_sample_stddev == value.compounded_daily_return == 0
    assert value.mean_volume_shares == Decimal("109.5")
    assert value.mean_turnover == Decimal("1009.5")
    assert value.sample_count == 20 and value.missing_fields == ()
    assert value.source_rank == 1 and value.degraded and not value.sizing_ready
    assert value.availability == "PROVIDER_TIME_ONLY"


def test_return_uses_each_provider_previous_close_not_unadjusted_adjacent_close():
    raw = history()
    bars = tuple(
        b.model_copy(update={"previous_close": Decimal("5") if i % 2 else Decimal("10")})
        for i, b in enumerate(raw.bars)
    )
    value = features(raw.model_copy(update={"bars": bars}))
    with localcontext(Context(prec=128)):
        assert value.daily_return_sample_stddev == (Decimal(5) / Decimal(19)).sqrt()
    assert value.compounded_daily_return == Decimal(1023)
    assert all(b.close == 10 for b in raw.bars)


def test_history_statistics_isolate_decimal_context_and_bind_raw_inputs():
    raw = history()
    normal = features(raw)
    with localcontext() as context:
        context.prec = 3
        context.traps[Inexact] = True
        assert features(raw) == normal
    changed = raw.model_copy(
        update={
            "bars": (raw.bars[0].model_copy(update={"turnover": Decimal("9999")}), *raw.bars[1:])
        }
    )
    assert features(changed).input_hash != normal.input_hash


@pytest.mark.parametrize("count", [1, 19])
def test_insufficient_observations_never_become_zero_statistics(count):
    value = features(history(count))
    assert value.sample_count == count
    assert value.daily_return_sample_stddev is value.mean_volume_shares is None
    assert value.missing_fields == ("INSUFFICIENT_20_OBSERVATIONS",)


def test_missing_fields_do_not_prevent_independent_known_statistics():
    raw = history()
    bars = (
        raw.bars[0].model_copy(update={"previous_close": None, "turnover": None}),
        *raw.bars[1:],
    )
    value = features(raw.model_copy(update={"bars": bars}))
    assert value.daily_return_sample_stddev is value.compounded_daily_return is None
    assert value.mean_turnover is None and value.mean_volume_shares == Decimal("109.5")
    assert value.missing_fields == ("PREVIOUS_CLOSE_MISSING", "TURNOVER_MISSING")


@pytest.mark.parametrize(
    "fault",
    ["foreign", "future", "old", "duplicate", "unordered", "float", "negative", "wrong_reference"],
)
def test_invalid_history_is_rejected_even_after_unvalidated_model_copy(fault):
    raw = history()
    bars = list(raw.bars)
    change = {
        "foreign": {"instrument_id": uuid4()},
        "future": {"as_of": NOW + timedelta(days=1)},
        "old": {"as_of": NOW - timedelta(days=90)},
        "float": {"close": 1.5},
        "negative": {"volume_shares": Decimal(-1)},
    }
    if fault in change:
        bars[0] = bars[0].model_copy(update=change[fault])
    if fault == "duplicate":
        bars[0] = bars[1]
    if fault == "unordered":
        bars.reverse()
    if fault == "wrong_reference":
        bars[-1] = bars[-1].model_copy(update={"as_of": NOW - timedelta(hours=1)})
    with pytest.raises((ValueError, TypeError, DomainError)):
        features(raw.model_copy(update={"bars": tuple(bars)}))


def test_history_reference_identity_close_and_old_valuation_compatibility():
    original = calculate()
    assert "target_historical_features" not in original.model_dump(mode="json")
    enriched = calculate(quotes={A: replace(quote(), history=history())})
    assert enriched.target_historical_features.sample_count == 20
    assert enriched.input_hash != original.input_hash
    for changed in (
        history().model_copy(update={"instrument_id": uuid4()}),
        history().model_copy(update={"reference_at": NOW - timedelta(days=1)}),
    ):
        with pytest.raises(ValueError):
            ensure_daily_bar(replace(quote(), history=changed))
    with pytest.raises(ValueError):
        ensure_daily_bar(replace(quote(price="11"), history=history()))


async def test_history_choice_changes_idempotency_but_false_preserves_legacy_hash():
    hashes = []

    class Port:
        async def submit(self, request_id, request_hash, prepare, *, retry_of):
            hashes.append(request_hash)

    service = AnalysisJobService(Port(), None)
    inp = StartAnalysisInput(uuid4(), uuid4(), "RESEARCH")
    await service.submit(uuid4(), inp)
    await service.submit(uuid4(), replace(inp, include_market_history=False))
    await service.submit(uuid4(), replace(inp, include_market_history=True))
    assert hashes[0] == hashes[1] and hashes[0] != hashes[2]
    assert "history_target_id" not in AnalysisMarketPlan().model_dump(mode="json")
