"""Normal, failure, and boundary tests for the PR-06 portfolio capacity slice."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from investment_os.domain.errors import DomainError
from investment_os.domain.policy import PositionPolicy
from investment_os.domain.portfolio import (
    PortfolioCapacityInputs,
    PortfolioPosition,
    PortfolioSnapshot,
    evaluate_portfolio_capacity,
)
from investment_os.domain.values import PositionBuckets, Quantity, UtcTimestamp, Weight


def _policy() -> PositionPolicy:
    return PositionPolicy(
        single_instrument_max=Weight(Decimal("0.08")),
        sector_max=Weight(Decimal("0.25")),
        gross_exposure_max=Weight(Decimal("1")),
        minimum_cash=Weight(Decimal("0.10")),
        core_ratio_target=Weight(Decimal("0.75")),
        tactical_ratio_target=Weight(Decimal("0.25")),
    )


def _inputs(**overrides: Weight) -> PortfolioCapacityInputs:
    values = {
        "instrument_weight": Weight(Decimal("0.02")),
        "sector_weight": Weight(Decimal("0.10")),
        "gross_exposure": Weight(Decimal("0.50")),
        "pending_instrument_weight": Weight(Decimal("0")),
        "pending_sector_weight": Weight(Decimal("0")),
        "pending_gross_exposure": Weight(Decimal("0")),
        "risk_budget_capacity": Weight(Decimal("1")),
        "liquidity_capacity": Weight(Decimal("1")),
    }
    values.update(overrides)
    return PortfolioCapacityInputs(**values)


def test_capacity_applies_all_portfolio_limits_and_preserves_pending_reservations() -> None:
    result = evaluate_portfolio_capacity(
        _policy(),
        _inputs(pending_instrument_weight=Weight(Decimal("0.03"))),
        Weight(Decimal("0.05")),
    )

    assert result.allowed_increase == Weight(Decimal("0.03"))
    assert not result.has_requested_capacity
    assert result.limits[0].code == "SINGLE_INSTRUMENT_CAP"
    assert result.limits[0].available == Weight(Decimal("0.03"))


def test_capacity_blocks_an_increase_when_the_sector_cap_is_exhausted() -> None:
    result = evaluate_portfolio_capacity(
        _policy(),
        _inputs(sector_weight=Weight(Decimal("0.25"))),
        Weight(Decimal("0.01")),
    )

    assert result.allowed_increase == Weight(Decimal("0"))
    assert not result.has_requested_capacity


def test_capacity_applies_risk_budget_and_liquidity_caps() -> None:
    result = evaluate_portfolio_capacity(
        _policy(),
        _inputs(
            risk_budget_capacity=Weight(Decimal("0.02")),
            liquidity_capacity=Weight(Decimal("0.01")),
        ),
        Weight(Decimal("0.05")),
    )

    assert result.allowed_increase == Weight(Decimal("0.01"))
    assert [limit.code for limit in result.limits[-2:]] == ["RISK_BUDGET_CAP", "LIQUIDITY_CAP"]


def test_portfolio_snapshot_rejects_duplicate_instruments_and_preserves_core_tactical_buckets() -> (
    None
):
    instrument_id = uuid4()
    position = PortfolioPosition(
        instrument_id=instrument_id,
        buckets=PositionBuckets(
            Quantity(Decimal("3")), Quantity(Decimal("2")), Quantity(Decimal("5"))
        ),
        average_cost=Decimal("10"),
        realized_pnl=Decimal("1"),
    )

    assert position.buckets.total == Quantity(Decimal("5"))
    with pytest.raises(DomainError, match="must not repeat an instrument"):
        PortfolioSnapshot(
            portfolio_id=uuid4(),
            as_of=UtcTimestamp(datetime(2026, 9, 20, tzinfo=UTC)),
            cash=Decimal("50"),
            nav=Decimal("100"),
            positions=(position, position),
        )


def test_snapshot_content_hash_is_order_independent_and_changes_with_cash() -> None:
    first_position = PortfolioPosition(
        uuid4(),
        PositionBuckets(Quantity(Decimal("1")), Quantity(Decimal("0")), Quantity(Decimal("1"))),
        Decimal("10"),
        Decimal("0"),
    )
    second_position = PortfolioPosition(
        uuid4(),
        PositionBuckets(Quantity(Decimal("2")), Quantity(Decimal("0")), Quantity(Decimal("2"))),
        Decimal("20"),
        Decimal("0"),
    )
    common = {
        "portfolio_id": uuid4(),
        "as_of": UtcTimestamp(datetime(2026, 9, 20, tzinfo=UTC)),
        "nav": Decimal("100"),
    }
    first = PortfolioSnapshot(
        cash=Decimal("50"), positions=(first_position, second_position), **common
    )
    reordered = PortfolioSnapshot(
        cash=Decimal("50"), positions=(second_position, first_position), **common
    )
    changed = PortfolioSnapshot(
        cash=Decimal("49"), positions=(first_position, second_position), **common
    )

    assert first.content_hash == reordered.content_hash
    assert first.content_hash != changed.content_hash
