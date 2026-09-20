"""Framework-free, evidence-first primitives for runtime Agent opinions.

These values intentionally contain no model-provider, prompt, persistence, or execution concern.
They are the trusted domain boundary reached only after a later application-layer schema validator
has rejected or repaired untrusted model output.
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.values import UtcTimestamp, Weight


class AgentRole(StrEnum):
    MACRO = "MACRO"
    INDUSTRY = "INDUSTRY"
    FUNDAMENTAL = "FUNDAMENTAL"
    MARKET_QUANT = "MARKET_QUANT"
    EVENT = "EVENT"
    PORTFOLIO = "PORTFOLIO"
    PORTFOLIO_MANAGER = "PORTFOLIO"
    RISK = "RISK"
    RISK_MANAGER = "RISK"
    DEVILS_ADVOCATE = "DEVILS_ADVOCATE"
    CIO = "CIO"
    REVIEW = "REVIEW"
    REVIEW_LEARNING = "REVIEW"


class AgentTool(StrEnum):
    """Closed capabilities that a role may receive through its prompt bundle."""

    RETRIEVE_EVIDENCE = "RETRIEVE_EVIDENCE"
    READ_THESIS = "READ_THESIS"


class OpinionStance(StrEnum):
    STRONGLY_NEGATIVE = "STRONGLY_NEGATIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    POSITIVE = "POSITIVE"
    STRONGLY_POSITIVE = "STRONGLY_POSITIVE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    # Backward-compatible internal spelling; the strict wire protocol accepts only NEUTRAL.
    MIXED = "NEUTRAL"


class ObservationMateriality(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ThesisImpactKind(StrEnum):
    STRENGTHEN = "STRENGTHEN"
    WEAKEN = "WEAKEN"
    BREAK = "BREAK"
    NONE = "NONE"


class RiskSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


def _require_text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise DomainError(
            DomainErrorCode.INVARIANT_VIOLATION,
            f"{field} must not be blank",
        )
    return normalized


def _normalize_text_items(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    return tuple(_require_text(value, field) for value in values)


@dataclass(frozen=True, slots=True)
class EvidenceBackedObservation:
    """A factual Agent statement whose provenance is explicit and non-empty."""

    statement: str
    evidence_ids: tuple[UUID, ...]
    materiality: ObservationMateriality = ObservationMateriality.MEDIUM

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement", _require_text(self.statement, "observation claim"))
        if not self.evidence_ids:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "a factual observation requires at least one Evidence reference",
            )
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "a factual observation must not repeat an Evidence reference",
            )

    @property
    def claim(self) -> str:
        """Compatibility accessor; the versioned wire field is `claim`."""

        return self.statement


@dataclass(frozen=True, slots=True)
class ThesisImpact:
    pillar_key: str
    impact: ThesisImpactKind
    reason: str
    evidence_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "pillar_key", _require_text(self.pillar_key, "pillar key"))
        object.__setattr__(self, "reason", _require_text(self.reason, "thesis impact reason"))
        if not self.evidence_ids or len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "a thesis impact requires unique Evidence references",
            )


@dataclass(frozen=True, slots=True)
class AgentRisk:
    code: str
    severity: RiskSeverity
    evidence_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _require_text(self.code, "risk code"))
        if not self.evidence_ids or len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "an Agent risk requires unique Evidence references",
            )


@dataclass(frozen=True, slots=True)
class InvalidationCondition:
    condition: str
    observable: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "condition", _require_text(self.condition, "invalidation condition")
        )
        object.__setattr__(
            self, "observable", _require_text(self.observable, "invalidation observable")
        )


@dataclass(frozen=True, slots=True)
class AgentOpinion:
    """Validated, structured research output; never a final Decision or execution instruction."""

    role: AgentRole
    instrument_id: UUID
    stance: OpinionStance
    confidence: Weight
    time_horizon: str
    observations: tuple[EvidenceBackedObservation, ...]
    assumptions: tuple[str, ...]
    unknowns: tuple[str, ...]
    risks: tuple[AgentRisk, ...]
    as_of: UtcTimestamp | None = None
    thesis_impacts: tuple[ThesisImpact, ...] = ()
    invalidation_conditions: tuple[InvalidationCondition, ...] = ()
    requested_followups: tuple[str, ...] = ()
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        object.__setattr__(self, "time_horizon", _require_text(self.time_horizon, "time horizon"))
        object.__setattr__(
            self, "schema_version", _require_text(self.schema_version, "schema version")
        )
        object.__setattr__(
            self, "assumptions", _normalize_text_items(self.assumptions, "assumption")
        )
        object.__setattr__(self, "unknowns", _normalize_text_items(self.unknowns, "unknown"))
        object.__setattr__(
            self,
            "requested_followups",
            _normalize_text_items(self.requested_followups, "requested followup"),
        )
        if self.schema_version != "1.0":
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "AgentOpinion requires the supported 1.0 schema",
            )
        if self.stance is OpinionStance.INSUFFICIENT_DATA:
            if self.observations:
                raise DomainError(
                    DomainErrorCode.INVARIANT_VIOLATION,
                    "an INSUFFICIENT_DATA opinion must not contain factual observations",
                )
            if self.confidence.value != 0:
                raise DomainError(
                    DomainErrorCode.INVARIANT_VIOLATION,
                    "an INSUFFICIENT_DATA opinion must have zero confidence",
                )
            return
        if not self.observations:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "a substantive AgentOpinion requires at least one evidence-backed observation",
            )
