from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from investment_os.domain.enums import InstrumentLifecycleState, ThesisState
from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.state_machines import (
    INSTRUMENT_TRANSITIONS,
    THESIS_TRANSITIONS,
    InstrumentTransitionContext,
    ThesisTransitionContext,
    transition_instrument,
    transition_thesis,
)
from investment_os.domain.values import PositionBuckets, Quantity, UtcTimestamp, Weight

NOW = UtcTimestamp(datetime(2026, 9, 17, tzinfo=UTC))
DECIMALS = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("1"),
    allow_nan=False,
    allow_infinity=False,
    places=6,
)


@given(value=DECIMALS)
def test_every_unit_interval_decimal_is_a_valid_weight(value: Decimal) -> None:
    assert Weight(value).value == value


@given(core=DECIMALS, tactical=DECIMALS)
def test_core_and_tactical_sum_is_preserved(core: Decimal, tactical: Decimal) -> None:
    total = core + tactical
    buckets = PositionBuckets(
        core=Quantity(core), tactical=Quantity(tactical), total=Quantity(total)
    )
    assert buckets.core.value + buckets.tactical.value == buckets.total.value


@given(core=DECIMALS, tactical=DECIMALS, difference=st.integers(min_value=1, max_value=10))
def test_any_inconsistent_reported_total_is_rejected(
    core: Decimal, tactical: Decimal, difference: int
) -> None:
    with pytest.raises(DomainError) as caught:
        PositionBuckets(
            core=Quantity(core),
            tactical=Quantity(tactical),
            total=Quantity(core + tactical + Decimal(difference)),
        )
    assert caught.value.code is DomainErrorCode.INVARIANT_VIOLATION


@given(
    current=st.sampled_from(list(InstrumentLifecycleState)),
    target=st.sampled_from(list(InstrumentLifecycleState)),
)
def test_instrument_state_machine_has_no_implicit_paths(
    current: InstrumentLifecycleState, target: InstrumentLifecycleState
) -> None:
    if target in INSTRUMENT_TRANSITIONS.get(current, frozenset()):
        return
    with pytest.raises(DomainError) as caught:
        transition_instrument(
            current,
            target,
            InstrumentTransitionContext(),
            reason_codes=("PROPERTY_CHECK",),
            occurred_at=NOW,
        )
    assert caught.value.code is DomainErrorCode.INVALID_TRANSITION


@given(
    current=st.sampled_from(list(ThesisState)),
    target=st.sampled_from(list(ThesisState)),
)
def test_thesis_state_machine_has_no_implicit_paths(
    current: ThesisState, target: ThesisState
) -> None:
    if target in THESIS_TRANSITIONS.get(current, frozenset()):
        return
    with pytest.raises(DomainError) as caught:
        transition_thesis(
            current,
            target,
            ThesisTransitionContext(),
            reason_codes=("PROPERTY_CHECK",),
            occurred_at=NOW,
        )
    assert caught.value.code is DomainErrorCode.INVALID_TRANSITION


def test_same_transition_input_is_deterministic() -> None:
    context = ThesisTransitionContext(evidence_supports_change=True, creates_new_version=True)
    first = transition_thesis(
        ThesisState.UNKNOWN,
        ThesisState.VALID,
        context,
        reason_codes=("NEW_PRIMARY_EVIDENCE",),
        occurred_at=NOW,
    )
    second = transition_thesis(
        ThesisState.UNKNOWN,
        ThesisState.VALID,
        context,
        reason_codes=("NEW_PRIMARY_EVIDENCE",),
        occurred_at=NOW,
    )
    assert first == second
