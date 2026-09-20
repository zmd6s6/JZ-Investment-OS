"""S3/S4/S6/S7 unit regressions for deterministic sizing."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from hypothesis import given
from hypothesis import strategies as st

from investment_os.domain.enums import Action, PositionBucket, RiskIntent, ThesisState
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
                (UUID("00000000-0000-0000-0000-000000000001"),),
                "Synthetic review clears risk.",
            ),
        )
    )
    now = UtcTimestamp(datetime(2026, 9, 20, tzinfo=UTC))
    return RiskAssessment(
        UUID("00000000-0000-0000-0000-000000000002"),
        1,
        now,
        UtcTimestamp(now.value + timedelta(days=1)),
        flags,
    )


def _request(
    action: Action,
    *,
    hard: bool = False,
    sector: Decimal = Decimal("0.10"),
    bucket: PositionBucket = PositionBucket.CORE,
    thesis_state: ThesisState = ThesisState.VALID,
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
            Weight(Decimal("1")),
            Weight(Decimal("1")),
        ),
        _policy(),
        _assessment(hard),
        thesis_state,
    )


def test_s3_veto_forces_buy_delta_to_zero() -> None:
    result = size_position(_formula(), _request(Action.BUY, hard=True))
    assert (
        result.delta_weight == 0
        and result.delta_quantity == 0
        and "RISK_VETO" in result.reason_codes
    )


def test_broken_thesis_cannot_increase_exposure() -> None:
    result = size_position(_formula(), _request(Action.ADD, thesis_state=ThesisState.BROKEN))

    assert result.delta_quantity == 0
    assert "THESIS_BROKEN" in result.reason_codes


def test_s4_core_hold_and_tactical_reduce_keep_actions_separate() -> None:
    core = size_position(_formula(), _request(Action.HOLD, bucket=PositionBucket.CORE))
    tactical = size_position(_formula(), _request(Action.REDUCE, bucket=PositionBucket.TACTICAL))
    assert core.delta_quantity == 0 and tactical.delta_quantity < 0


def test_s6_sector_capacity_blocks_buy_and_s7_equal_inputs_are_bit_identical() -> None:
    blocked = size_position(_formula(), _request(Action.BUY, sector=Decimal("0.25")))
    first = size_position(_formula(), _request(Action.BUY))
    second = size_position(_formula(), _request(Action.BUY))
    assert (
        blocked.delta_quantity == 0
        and "SECTOR_CAP" in blocked.reason_codes
        and blocked.capacity.requested_increase == Weight(Decimal("0.03"))
    )
    assert first == second and first.input_hash == second.input_hash
    assert blocked.input_hash != first.input_hash


def test_formula_configuration_and_risk_assessment_are_replay_inputs() -> None:
    request = _request(Action.BUY)
    baseline = size_position(_formula(), request)
    constrained = size_position(replace(_formula(), volatility_scale_max=Decimal("0.75")), request)
    vetoed = size_position(_formula(), _request(Action.BUY, hard=True))

    assert constrained.input_hash != baseline.input_hash
    assert constrained.delta_weight < baseline.delta_weight
    assert vetoed.input_hash != baseline.input_hash


@given(sector=st.decimals(min_value=Decimal("0"), max_value=Decimal("1"), places=4))
def test_buy_never_exceeds_requested_capacity_or_increases_risk_through_rounding(
    sector: Decimal,
) -> None:
    result = size_position(_formula(), _request(Action.BUY, sector=sector))

    assert result.delta_weight <= result.capacity.requested_increase.value
    assert result.delta_quantity <= result.pre_rounding_delta_quantity
