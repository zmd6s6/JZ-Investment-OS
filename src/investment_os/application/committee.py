"""Deterministic, bounded committee planning without Decisions or execution behavior."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from investment_os.domain.agent import AgentOpinion, AgentRole, OpinionStance
from investment_os.domain.errors import DomainError, DomainErrorCode

ROUND_ONE_ROLES: Final[tuple[AgentRole, ...]] = (
    AgentRole.MACRO,
    AgentRole.INDUSTRY,
    AgentRole.FUNDAMENTAL,
    AgentRole.MARKET_QUANT,
    AgentRole.EVENT,
)


class CommitteeConflictKind(StrEnum):
    STANCE_SPREAD = "STANCE_SPREAD"


@dataclass(frozen=True, slots=True)
class CommitteeConflict:
    """A deterministic material disagreement, expressed without model-generated summary text."""

    kind: CommitteeConflictKind
    roles: tuple[AgentRole, ...]
    stances: tuple[tuple[AgentRole, OpinionStance], ...]

    def __post_init__(self) -> None:
        if len(self.roles) < 2 or len(set(self.roles)) != len(self.roles):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "a committee conflict requires at least two distinct roles",
            )
        if tuple(sorted(self.roles, key=str)) != self.roles:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "committee conflict roles must have deterministic ordering",
            )


@dataclass(frozen=True, slots=True)
class CommitteeRound:
    """A finite execution plan; only rounds one and two are representable."""

    number: int
    roles: tuple[AgentRole, ...]
    conflicts: tuple[CommitteeConflict, ...] = ()

    def __post_init__(self) -> None:
        if self.number not in (1, 2):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "committee plans permit only rounds one and two",
            )
        if not self.roles or len(set(self.roles)) != len(self.roles):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "committee round roles must be non-empty and distinct",
            )
        if self.number == 1 and (self.roles != ROUND_ONE_ROLES or self.conflicts):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "round one must contain only the independent required specialist roles",
            )
        if self.number == 2 and AgentRole.DEVILS_ADVOCATE not in self.roles:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "round two must include Devil's Advocate",
            )


def plan_round_one() -> CommitteeRound:
    """Construct the fixed, independent specialist round mandated by the protocol."""

    return CommitteeRound(number=1, roles=ROUND_ONE_ROLES)


def detect_stance_conflicts(opinions: tuple[AgentOpinion, ...]) -> tuple[CommitteeConflict, ...]:
    """Detect only a polar stance spread, without inventing confidence thresholds or prose."""

    if len({opinion.role for opinion in opinions}) != len(opinions):
        raise DomainError(
            DomainErrorCode.INVARIANT_VIOLATION,
            "committee conflict detection requires at most one opinion per role",
        )
    if len({opinion.instrument_id for opinion in opinions}) > 1:
        raise DomainError(
            DomainErrorCode.INVARIANT_VIOLATION,
            "committee conflict detection requires one instrument",
        )

    polar_opinions = tuple(
        opinion
        for opinion in opinions
        if opinion.stance in (OpinionStance.POSITIVE, OpinionStance.NEGATIVE)
    )
    stances = {opinion.stance for opinion in polar_opinions}
    if stances != {OpinionStance.POSITIVE, OpinionStance.NEGATIVE}:
        return ()

    ordered = tuple(sorted(polar_opinions, key=lambda opinion: str(opinion.role)))
    return (
        CommitteeConflict(
            kind=CommitteeConflictKind.STANCE_SPREAD,
            roles=tuple(opinion.role for opinion in ordered),
            stances=tuple((opinion.role, opinion.stance) for opinion in ordered),
        ),
    )


def plan_round_two(conflicts: tuple[CommitteeConflict, ...]) -> CommitteeRound:
    """Target only conflicting specialists, while always scheduling Devil's Advocate review."""

    targeted_roles = {role for conflict in conflicts for role in conflict.roles}
    targeted_roles.add(AgentRole.DEVILS_ADVOCATE)
    return CommitteeRound(
        number=2,
        roles=tuple(sorted(targeted_roles, key=str)),
        conflicts=conflicts,
    )
