from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.values import (
    PositionBuckets,
    Quantity,
    UtcTimestamp,
    Weight,
    exact_decimal,
)


def test_exact_decimal_preserves_exact_values() -> None:
    assert exact_decimal("0.10") == Decimal("0.10")
    assert exact_decimal(2) == Decimal("2")
    assert exact_decimal(Decimal("3.5")) == Decimal("3.5")


@pytest.mark.parametrize("value", [0.1, True])
def test_exact_decimal_rejects_binary_float_and_bool(value: object) -> None:
    with pytest.raises(DomainError) as caught:
        exact_decimal(value)  # type: ignore[arg-type]
    assert caught.value.code is DomainErrorCode.FLOAT_NOT_ALLOWED


@pytest.mark.parametrize("value", ["not-a-number", "NaN", "Infinity"])
def test_exact_decimal_rejects_invalid_or_non_finite_values(value: str) -> None:
    with pytest.raises(DomainError) as caught:
        exact_decimal(value)
    assert caught.value.code is DomainErrorCode.NON_FINITE_DECIMAL


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("0.25"), Decimal("1")])
def test_weight_accepts_closed_unit_interval(value: Decimal) -> None:
    assert Weight(value).value == value


@pytest.mark.parametrize("value", [Decimal("-0.01"), Decimal("1.01")])
def test_weight_rejects_values_outside_unit_interval(value: Decimal) -> None:
    with pytest.raises(DomainError) as caught:
        Weight(value)
    assert caught.value.code is DomainErrorCode.OUT_OF_RANGE


def test_quantity_rejects_negative_value() -> None:
    with pytest.raises(DomainError, match="must not be negative"):
        Quantity(Decimal("-1"))


def test_utc_timestamp_normalizes_aware_timestamp() -> None:
    source = datetime(2026, 9, 17, 18, tzinfo=timezone(timedelta(hours=8)))
    timestamp = UtcTimestamp(source)
    assert timestamp.value.tzinfo is UTC
    assert timestamp.value.hour == 10


def test_utc_timestamp_rejects_naive_datetime() -> None:
    with pytest.raises(DomainError) as caught:
        UtcTimestamp(datetime(2026, 9, 17))
    assert caught.value.code is DomainErrorCode.TIMEZONE_REQUIRED


def test_core_and_tactical_must_equal_total_position() -> None:
    position = PositionBuckets(
        core=Quantity(Decimal("7")),
        tactical=Quantity(Decimal("3")),
        total=Quantity(Decimal("10")),
    )
    assert position.total.value == Decimal("10")


def test_inconsistent_position_buckets_fail_closed() -> None:
    with pytest.raises(DomainError) as caught:
        PositionBuckets(
            core=Quantity(Decimal("7")),
            tactical=Quantity(Decimal("3")),
            total=Quantity(Decimal("11")),
        )
    assert caught.value.code is DomainErrorCode.INVARIANT_VIOLATION
