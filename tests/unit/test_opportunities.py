"""Real formulas and source/period guards for the finite query funnel."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal, getcontext
from uuid import uuid4

import pytest
from pydantic import ValidationError

from investment_os.application.instrument_catalog import InstrumentCatalogEntry
from investment_os.application.market_data import (
    MarketDataRequest,
    MarketDataSnapshot,
    MarketQuote,
    QuoteProvenance,
)
from investment_os.application.opportunities import (
    FactSnapshot,
    FunnelQuery,
    ManualScreenFacts,
    evaluate,
)

NOW = datetime(2026, 10, 27, tzinfo=UTC)


def inputs(**changes):
    identifier = uuid4()
    evidence_id = uuid4()
    entry = InstrumentCatalogEntry(
        instrument_id=identifier,
        market="SSE",
        symbol="629402",
        name="合成研究",
        asset_type="EQUITY",
        currency="CNY",
        sector="Synthetic",
    )
    query = FunnelQuery(
        request_id=uuid4(),
        instrument_ids=(identifier,),
        scope_name="合成本地范围",
        scope_locator="synthetic://scope",
        quote_source_name="合成行情",
        fact_source_name="合成年报",
        as_of=NOW,
        candidate_limit=2,
        min_profit_margin="0.1",
        min_revenue_growth="0.1",
        max_pe="60",
        min_price_change="0",
    )
    facts = ManualScreenFacts(
        request_id=uuid4(),
        instrument_id=identifier,
        source_name=query.fact_source_name,
        source_locator="synthetic://facts",
        observed_at=NOW - timedelta(days=2),
        effective_at=NOW - timedelta(days=2),
        available_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=1),
        revenue_current="100",
        revenue_previous="80",
        net_income="20",
        annual_diluted_shares="100",
        previous_close="8",
        previous_close_at=NOW - timedelta(days=2),
        suspended=False,
        industry="Synthetic",
        fiscal_year=2025,
        financial_basis="CALENDAR_YEAR_CONSOLIDATED_CNY",
        net_income_basis="ATTRIBUTABLE_TO_ORDINARY_SHAREHOLDERS",
        quote_evidence_id=evidence_id,
        same_share_basis=True,
    )
    if changes:
        facts = ManualScreenFacts.model_validate(facts.model_dump() | changes)
    provenance = QuoteProvenance(
        instrument_id=identifier,
        evidence_id=evidence_id,
        content_hash="a" * 64,
        source_name=query.quote_source_name,
        source_locator="synthetic://quote",
        currency="CNY",
        observed_at=NOW - timedelta(hours=1),
        effective_at=NOW - timedelta(hours=1),
        available_at=NOW - timedelta(hours=1),
        ingested_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    quote = MarketDataSnapshot(
        **MarketDataRequest(
            instrument_id=identifier,
            source="MANUAL_MARKET",
            source_name=query.quote_source_name,
            as_of=NOW,
        ).model_dump(exclude={"portfolio_id"}),
        status="AVAILABLE",
        reason_code="MANUAL_UNVERIFIED",
        quote=MarketQuote(price=Decimal("10"), provenance=provenance),
        provenance=provenance,
    )
    snapshot = FactSnapshot(
        status="AVAILABLE", facts=facts, evidence_id=uuid4(), content_hash="b" * 64, ingested_at=NOW
    )
    return entry, quote, snapshot, query


def test_annual_same_share_basis_computes_exact_research_features_without_trade_action():
    entry, quote, facts, query = inputs()
    result = evaluate(entry, quote, facts, query)
    assert result.candidate
    assert result.features == {
        "profit_margin": "0.2",
        "revenue_growth": "0.25",
        "pe": "50",
        "price_change": "0.25",
    }
    assert result.lifecycle_state is None
    assert all(stage.status == "PASSED" for stage in result.stages)
    assert len(result.evidence_ids) == 2
    assert "action" not in type(result).model_fields


@pytest.mark.parametrize(
    "missing",
    [
        "net_income",
        "revenue_current",
        "fiscal_year",
        "financial_basis",
        "net_income_basis",
        "annual_diluted_shares",
        "revenue_previous",
        "previous_close",
        "previous_close_at",
        "same_share_basis",
        "quote_evidence_id",
    ],
)
def test_missing_or_ambiguous_period_and_basis_cannot_become_candidate(missing):
    entry, quote, facts, query = inputs(**{missing: None})
    result = evaluate(entry, quote, facts, query)
    assert not result.candidate
    assert any(s.status == "MISSING" for s in result.stages)


@pytest.mark.parametrize(
    "change",
    [
        {"revenue_current": 10.5},
        {"net_income": True},
        {"annual_diluted_shares": "0"},
        {"fiscal_year": 2027},
        {"observed_at": NOW.replace(tzinfo=None)},
        {"available_at": NOW - timedelta(days=3)},
    ],
)
def test_facts_reject_float_invalid_denominator_future_period_and_naive_time(change):
    with pytest.raises(ValidationError):
        inputs(**change)


def test_numerical_rejection_is_visible_and_never_upgrades_lifecycle():
    entry, quote, facts, query = inputs(net_income="1")
    result = evaluate(entry, quote, facts, query)
    assert not result.candidate
    assert result.stages[1].status == "REJECTED"
    assert result.lifecycle_state is None


def test_global_decimal_context_does_not_change_formula_output():
    values = inputs()
    expected = evaluate(*values).features
    original = getcontext().prec
    try:
        getcontext().prec = 2
        assert evaluate(*values).features == expected
    finally:
        getcontext().prec = original


def test_industry_is_evidence_fact_and_query_filter_is_explicit():
    entry, quote, facts, query = inputs()
    blocked = evaluate(
        entry, quote, facts, query.model_copy(update={"industry_filter": "Different"})
    )
    assert not blocked.candidate
    assert next(s for s in blocked.stages if s.stage == "GROWTH_VALUATION").status == "REJECTED"
    unknown = evaluate(
        entry,
        quote,
        facts.model_copy(update={"facts": facts.facts.model_copy(update={"industry": None})}),
        query,
    )
    assert not unknown.candidate
    assert next(s for s in unknown.stages if s.stage == "GROWTH_VALUATION").status == "MISSING"
