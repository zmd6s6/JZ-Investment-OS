"""Framework-free value objects for exact financial and time semantics."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from investment_os.domain.errors import DomainError, DomainErrorCode


def exact_decimal(value: Decimal | int | str) -> Decimal:
    """Create a finite Decimal while rejecting binary floating-point inputs."""

    if isinstance(value, (bool, float)):
        raise DomainError(
            DomainErrorCode.FLOAT_NOT_ALLOWED,
            "financial values must not use bool or binary float",
        )
    try:
        result = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise DomainError(
            DomainErrorCode.NON_FINITE_DECIMAL,
            "value is not a valid decimal",
            details={"value": str(value)},
        ) from exc
    if not result.is_finite():
        raise DomainError(
            DomainErrorCode.NON_FINITE_DECIMAL,
            "financial values must be finite",
            details={"value": str(value)},
        )
    return result


@dataclass(frozen=True, slots=True)
class Weight:
    value: Decimal

    def __post_init__(self) -> None:
        normalized = exact_decimal(self.value)
        if not Decimal("0") <= normalized <= Decimal("1"):
            raise DomainError(
                DomainErrorCode.OUT_OF_RANGE,
                "weight must be between zero and one",
                details={"value": str(normalized)},
            )
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True, slots=True)
class Quantity:
    value: Decimal

    def __post_init__(self) -> None:
        normalized = exact_decimal(self.value)
        if normalized < 0:
            raise DomainError(
                DomainErrorCode.OUT_OF_RANGE,
                "quantity must not be negative",
                details={"value": str(normalized)},
            )
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True, slots=True)
class UtcTimestamp:
    value: datetime

    def __post_init__(self) -> None:
        if self.value.tzinfo is None or self.value.utcoffset() is None:
            raise DomainError(
                DomainErrorCode.TIMEZONE_REQUIRED,
                "timestamp must be timezone-aware",
            )
        object.__setattr__(self, "value", self.value.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class PositionBuckets:
    """A reported position whose Core and Tactical quantities remain explicit."""

    core: Quantity
    tactical: Quantity
    total: Quantity

    def __post_init__(self) -> None:
        computed = self.core.value + self.tactical.value
        if computed != self.total.value:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "core plus tactical quantity must equal total quantity",
                details={"computed": str(computed), "reported": str(self.total.value)},
            )
