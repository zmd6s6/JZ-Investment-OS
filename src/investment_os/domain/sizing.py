"""Pure, versioned Decimal position sizing with conservative lot rounding."""

import json
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from hashlib import sha256

from investment_os.domain.enums import Action, PositionBucket, RiskIntent
from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.policy import PositionPolicy
from investment_os.domain.portfolio import (
    PortfolioCapacity,
    PortfolioCapacityInputs,
    evaluate_portfolio_capacity,
)
from investment_os.domain.risk import RiskAssessment
from investment_os.domain.values import Quantity, Weight, exact_decimal


def _positive(value: Decimal | int | str, field: str) -> Decimal:
    normalized = exact_decimal(value)
    if normalized <= 0:
        raise DomainError(DomainErrorCode.OUT_OF_RANGE, f"{field} must be positive")
    return normalized


@dataclass(frozen=True, slots=True)
class SizingFormula:
    version: str
    intent_weights: dict[RiskIntent, Weight]
    target_volatility: Decimal
    volatility_floor: Decimal
    volatility_scale_min: Decimal
    volatility_scale_max: Decimal
    reduce_fraction: Weight

    def __post_init__(self) -> None:
        if not self.version.strip() or set(self.intent_weights) != set(RiskIntent):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION, "formula must define every intent"
            )
        target_volatility = _positive(self.target_volatility, "target volatility")
        volatility_floor = _positive(self.volatility_floor, "volatility floor")
        scale_min = _positive(self.volatility_scale_min, "minimum volatility scale")
        scale_max = _positive(self.volatility_scale_max, "maximum volatility scale")
        if scale_min > scale_max:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION, "volatility scale range is invalid"
            )
        object.__setattr__(self, "target_volatility", target_volatility)
        object.__setattr__(self, "volatility_floor", volatility_floor)
        object.__setattr__(self, "volatility_scale_min", scale_min)
        object.__setattr__(self, "volatility_scale_max", scale_max)


@dataclass(frozen=True, slots=True)
class SizingRequest:
    action: Action
    bucket: PositionBucket
    risk_intent: RiskIntent
    current_bucket_weight: Weight
    current_bucket_quantity: Quantity
    nav: Decimal
    reference_price: Decimal
    lot_size: Quantity
    instrument_volatility: Decimal
    capacity_inputs: PortfolioCapacityInputs
    policy: PositionPolicy
    risk_assessment: RiskAssessment

    def __post_init__(self) -> None:
        object.__setattr__(self, "nav", _positive(self.nav, "NAV"))
        object.__setattr__(
            self, "reference_price", _positive(self.reference_price, "reference price")
        )
        object.__setattr__(
            self, "instrument_volatility", _positive(self.instrument_volatility, "volatility")
        )
        if self.lot_size.value <= 0:
            raise DomainError(DomainErrorCode.OUT_OF_RANGE, "lot size must be positive")


@dataclass(frozen=True, slots=True)
class PositionSizingResult:
    formula_version: str
    input_hash: str
    target_weight: Weight
    delta_weight: Decimal
    target_quantity: Quantity
    delta_quantity: Decimal
    pre_rounding_delta_quantity: Decimal
    capacity: PortfolioCapacity
    reason_codes: tuple[str, ...]


def _round_delta(delta: Decimal, lot_size: Decimal, current: Decimal) -> Decimal:
    lots = abs(delta) / lot_size
    if delta >= 0:
        return lots.to_integral_value(rounding=ROUND_FLOOR) * lot_size
    return -min(current, lots.to_integral_value(rounding=ROUND_CEILING) * lot_size)


def _input_hash(formula: SizingFormula, request: SizingRequest) -> str:
    payload = {
        "formula_version": formula.version,
        "action": request.action.value,
        "bucket": request.bucket.value,
        "risk_intent": request.risk_intent.value,
        "current_bucket_weight": str(request.current_bucket_weight.value),
        "current_bucket_quantity": str(request.current_bucket_quantity.value),
        "nav": str(request.nav),
        "reference_price": str(request.reference_price),
        "lot_size": str(request.lot_size.value),
        "instrument_volatility": str(request.instrument_volatility),
        "risk_gate": request.risk_assessment.gate.value,
        "capacity_inputs": {
            "instrument_weight": str(request.capacity_inputs.instrument_weight.value),
            "sector_weight": str(request.capacity_inputs.sector_weight.value),
            "gross_exposure": str(request.capacity_inputs.gross_exposure.value),
            "pending_instrument_weight": str(
                request.capacity_inputs.pending_instrument_weight.value
            ),
            "pending_sector_weight": str(request.capacity_inputs.pending_sector_weight.value),
            "pending_gross_exposure": str(request.capacity_inputs.pending_gross_exposure.value),
        },
        "position_policy": {
            "single_instrument_max": str(request.policy.single_instrument_max.value),
            "sector_max": str(request.policy.sector_max.value),
            "gross_exposure_max": str(request.policy.gross_exposure_max.value),
            "minimum_cash": str(request.policy.minimum_cash.value),
        },
        "intent_weights": {
            key.value: str(value.value) for key, value in formula.intent_weights.items()
        },
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def size_position(formula: SizingFormula, request: SizingRequest) -> PositionSizingResult:
    """Return a repeatable result; VETO and capacity can only reduce BUY/ADD exposure."""

    current = request.current_bucket_weight.value
    reasons: list[str] = []
    capacity = evaluate_portfolio_capacity(
        request.policy, request.capacity_inputs, Weight(Decimal("0"))
    )
    if request.action in {Action.BUY, Action.ADD}:
        if not request.risk_assessment.permits_action(request.action):
            target = current
            reasons.append("RISK_VETO")
        else:
            scale = formula.target_volatility / max(
                request.instrument_volatility, formula.volatility_floor
            )
            scale = min(max(scale, formula.volatility_scale_min), formula.volatility_scale_max)
            raw_target = formula.intent_weights[request.risk_intent].value * scale
            requested = Weight(max(Decimal("0"), raw_target - current))
            capacity = evaluate_portfolio_capacity(
                request.policy, request.capacity_inputs, requested
            )
            target = current + capacity.allowed_increase.value
            if not capacity.has_requested_capacity:
                reasons.extend(
                    limit.code
                    for limit in capacity.limits
                    if limit.available.value < requested.value
                )
    elif request.action is Action.REDUCE:
        target = current * (Decimal("1") - formula.reduce_fraction.value)
        reasons.append("DETERMINISTIC_REDUCE")
    elif request.action is Action.EXIT:
        target = Decimal("0")
        reasons.append("EXIT")
    else:
        target = current
        reasons.append("NO_EXPOSURE_CHANGE")

    delta_weight = target - current
    raw_delta_quantity = delta_weight * request.nav / request.reference_price
    rounded_delta = _round_delta(
        raw_delta_quantity, request.lot_size.value, request.current_bucket_quantity.value
    )
    target_quantity = Quantity(request.current_bucket_quantity.value + rounded_delta)
    return PositionSizingResult(
        formula_version=formula.version,
        input_hash=_input_hash(formula, request),
        target_weight=Weight(target),
        delta_weight=delta_weight,
        target_quantity=target_quantity,
        delta_quantity=rounded_delta,
        pre_rounding_delta_quantity=raw_delta_quantity,
        capacity=capacity,
        reason_codes=tuple(sorted(set(reasons))),
    )
