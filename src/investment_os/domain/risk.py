"""Immutable, evidence-backed Risk assessments that cannot be overridden by Agents."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from investment_os.domain.enums import Action, RiskGateState
from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.values import UtcTimestamp


class RiskFlagKind(StrEnum):
    HARD = "HARD"
    SOFT = "SOFT"


class RiskSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


def _require_text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise DomainError(DomainErrorCode.INVARIANT_VIOLATION, f"{field} must not be blank")
    return normalized


@dataclass(frozen=True, slots=True)
class RiskFlag:
    """A machine-readable risk fact with its Evidence and release condition."""

    code: str
    kind: RiskFlagKind
    severity: RiskSeverity
    evidence_ids: tuple[UUID, ...]
    release_condition: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _require_text(self.code, "risk flag code"))
        object.__setattr__(
            self,
            "release_condition",
            _require_text(self.release_condition, "risk flag release condition"),
        )
        if not self.evidence_ids or len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "a risk flag requires unique Evidence references",
            )


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    """A versioned immutable PASS or VETO record for one as-of risk evaluation."""

    id: UUID
    version: int
    as_of: UtcTimestamp
    expires_at: UtcTimestamp
    flags: tuple[RiskFlag, ...]

    def __post_init__(self) -> None:
        if self.version <= 0:
            raise DomainError(DomainErrorCode.INVARIANT_VIOLATION, "risk version must be positive")
        if self.expires_at.value <= self.as_of.value:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "risk assessment expiry must follow its as-of time",
            )
        codes = tuple(flag.code for flag in self.flags)
        if len(set(codes)) != len(codes):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "a risk assessment must not repeat a reason code",
            )

    @property
    def gate(self) -> RiskGateState:
        if any(flag.kind is RiskFlagKind.HARD for flag in self.flags):
            return RiskGateState.VETO
        return RiskGateState.PASS

    @property
    def evidence_ids(self) -> tuple[UUID, ...]:
        return tuple(evidence_id for flag in self.flags for evidence_id in flag.evidence_ids)

    def permits_action(self, action: Action) -> bool:
        """A VETO blocks only risk-increasing actions; reducing risk remains available."""

        return self.gate is RiskGateState.PASS or action in {Action.REDUCE, Action.EXIT}

    def is_active_at(self, as_of: UtcTimestamp) -> bool:
        """An assessment expires before it can authorize risk at its expiry instant."""

        return as_of.value < self.expires_at.value
