"""Tests for deterministic, two-round committee planning."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from investment_os.application.committee import (
    ROUND_ONE_ROLES,
    CommitteeConflict,
    CommitteeConflictKind,
    CommitteeRound,
    detect_stance_conflicts,
    plan_round_one,
    plan_round_two,
)
from investment_os.domain.agent import (
    AgentOpinion,
    AgentRole,
    EvidenceBackedObservation,
    OpinionStance,
)
from investment_os.domain.errors import DomainError
from investment_os.domain.values import Weight


def _opinion(
    role: AgentRole,
    stance: OpinionStance,
    *,
    instrument_id: UUID | None = None,
) -> AgentOpinion:
    substantive = stance is not OpinionStance.INSUFFICIENT_DATA
    return AgentOpinion(
        role=role,
        instrument_id=instrument_id if instrument_id is not None else uuid4(),
        stance=stance,
        confidence=Weight(Decimal("0.5") if substantive else Decimal("0")),
        time_horizon="synthetic horizon",
        observations=(
            (EvidenceBackedObservation("Synthetic fact", (uuid4(),)),) if substantive else ()
        ),
        assumptions=(),
        unknowns=("Synthetic unavailable data",) if not substantive else (),
        risks=(),
    )


def test_round_one_has_only_the_fixed_independent_specialist_roles() -> None:
    round_one = plan_round_one()

    assert round_one.number == 1
    assert round_one.roles == ROUND_ONE_ROLES
    assert round_one.conflicts == ()


def test_polar_stances_produce_one_deterministically_ordered_material_conflict() -> None:
    instrument_id = uuid4()
    conflict = detect_stance_conflicts(
        (
            _opinion(AgentRole.EVENT, OpinionStance.NEGATIVE, instrument_id=instrument_id),
            _opinion(AgentRole.MACRO, OpinionStance.POSITIVE, instrument_id=instrument_id),
            _opinion(AgentRole.INDUSTRY, OpinionStance.MIXED, instrument_id=instrument_id),
        )
    )

    assert conflict[0].kind is CommitteeConflictKind.STANCE_SPREAD
    assert conflict[0].roles == (AgentRole.EVENT, AgentRole.MACRO)


def test_round_two_targets_conflicted_roles_and_always_includes_devils_advocate() -> None:
    instrument_id = uuid4()
    conflicts = detect_stance_conflicts(
        (
            _opinion(AgentRole.MACRO, OpinionStance.POSITIVE, instrument_id=instrument_id),
            _opinion(AgentRole.FUNDAMENTAL, OpinionStance.NEGATIVE, instrument_id=instrument_id),
        )
    )

    round_two = plan_round_two(conflicts)

    assert round_two.number == 2
    assert round_two.roles == (
        AgentRole.DEVILS_ADVOCATE,
        AgentRole.FUNDAMENTAL,
        AgentRole.MACRO,
    )
    assert round_two.conflicts == conflicts


def test_no_material_conflict_still_schedules_only_devils_advocate_for_round_two() -> None:
    instrument_id = uuid4()
    conflicts = detect_stance_conflicts(
        (
            _opinion(AgentRole.MACRO, OpinionStance.MIXED, instrument_id=instrument_id),
            _opinion(AgentRole.EVENT, OpinionStance.POSITIVE, instrument_id=instrument_id),
        )
    )

    assert conflicts == ()
    assert plan_round_two(conflicts).roles == (AgentRole.DEVILS_ADVOCATE,)


def test_committee_rejects_a_third_round_and_duplicate_role_opinions() -> None:
    with pytest.raises(DomainError, match="only rounds one and two"):
        CommitteeRound(number=3, roles=(AgentRole.DEVILS_ADVOCATE,))
    with pytest.raises(DomainError, match="must include Devil"):
        CommitteeRound(number=2, roles=(AgentRole.MACRO,))

    opinion = _opinion(AgentRole.MACRO, OpinionStance.POSITIVE)
    with pytest.raises(DomainError, match="at most one opinion per role"):
        detect_stance_conflicts((opinion, opinion))


def test_conflict_requires_one_instrument_and_valid_deterministic_roles() -> None:
    with pytest.raises(DomainError, match="one instrument"):
        detect_stance_conflicts(
            (
                _opinion(AgentRole.MACRO, OpinionStance.POSITIVE),
                _opinion(AgentRole.EVENT, OpinionStance.NEGATIVE),
            )
        )

    with pytest.raises(DomainError, match="deterministic ordering"):
        CommitteeConflict(
            kind=CommitteeConflictKind.STANCE_SPREAD,
            roles=(AgentRole.MACRO, AgentRole.EVENT),
            stances=(
                (AgentRole.MACRO, OpinionStance.POSITIVE),
                (AgentRole.EVENT, OpinionStance.NEGATIVE),
            ),
        )
