"""S3/S4/S6/S7 unit regressions for deterministic sizing."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from investment_os.domain.enums import Action, PositionBucket, RiskIntent
from investment_os.domain.policy import PositionPolicy
from investment_os.domain.portfolio import PortfolioCapacityInputs
from investment_os.domain.risk import RiskAssessment, RiskFlag, RiskFlagKind, RiskSeverity
from investment_os.domain.sizing import SizingFormula, SizingRequest, size_position
from investment_os.domain.values import Quantity, UtcTimestamp, Weight


def _formula() -> SizingFormula:
    return SizingFormula(
        version="test-v1",
        intent_weights={intent: Weight(Decimal("0")) for intent in RiskIntent}
        | {RiskIntent.NORMAL: Weight(Decimal("0.05"))},
        target_volatility=Decimal("0.20"),
        volatility_floor=Decimal("0.10"),
        volatility_scale_min=Decimal("0.5"),
        volatility_scale_max=Decimal("1"),
        reduce_fraction=Weight(Decimal("0.50")),
    )


def _policy() -> PositionPolicy:
    return PositionPolicy(
        Weight(Decimal("0.08")),
        Weight(Decimal("0.25")),
        Weight(Decimal("1")),
        Weight(Decimal("0.10")),
        Weight(Decimal("0.75")),
        Weight(Decimal("0.25")),
    )


def _assessment(hard: bool = False) -> RiskAssessment:
    flags = (
        ()
        if not hard
        else (
            RiskFlag(
                "SYNTHETIC_HARD_RISK",
                RiskFlagKind.HARD,
                RiskSeverity.HIGH,
                (uuid4(),),
                "Synthetic review clears risk.",
            ),
        )
    )
    now = UtcTimestamp(datetime(2026, 9, 20, tzinfo=UTC))
    return RiskAssessment(uuid4(), 1, now, UtcTimestamp(now.value + timedelta(days=1)), flags)


def _request(
    action: Action,
    *,
    hard: bool = False,
    sector: Decimal = Decimal("0.10"),
    bucket: PositionBucket = PositionBucket.CORE,
) -> SizingRequest:
    return SizingRequest(
        action,
        bucket,
        RiskIntent.NORMAL,
        Weight(Decimal("0.02")),
        Quantity(Decimal("2")),
        Decimal("1000"),
        Decimal("10"),
        Quantity(Decimal("1")),
        Decimal("0.20"),
        PortfolioCapacityInputs(
            Weight(Decimal("0.02")),
            Weight(sector),
            Weight(Decimal("0.50")),
            Weight(Decimal("0")),
            Weight(Decimal("0")),
            Weight(Decimal("0")),
        ),
        _policy(),
        _assessment(hard),
    )


def test_s3_veto_forces_buy_delta_to_zero() -> None:
    result = size_position(_formula(), _request(Action.BUY, hard=True))
    assert (
        result.delta_weight == 0
        and result.delta_quantity == 0
        and "RISK_VETO" in result.reason_codes
    )


def test_s4_core_hold_and_tactical_reduce_keep_actions_separate() -> None:
    core = size_position(_formula(), _request(Action.HOLD, bucket=PositionBucket.CORE))
    tactical = size_position(_formula(), _request(Action.REDUCE, bucket=PositionBucket.TACTICAL))
    assert core.delta_quantity == 0 and tactical.delta_quantity < 0


def test_s6_sector_capacity_blocks_buy_and_s7_equal_inputs_are_bit_identical() -> None:
    blocked = size_position(_formula(), _request(Action.BUY, sector=Decimal("0.25")))
    first = size_position(_formula(), _request(Action.BUY))
    second = size_position(_formula(), _request(Action.BUY))
    assert blocked.delta_quantity == 0 and "SECTOR_CAP" in blocked.reason_codes
    assert first == second and first.input_hash == second.input_hash
