"""Framework-free, evidence-first primitives for runtime Agent opinions.

These values intentionally contain no model-provider, prompt, persistence, or execution concern.
They are the trusted domain boundary reached only after a later application-layer schema validator
has rejected or repaired untrusted model output.
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.values import Weight


class AgentRole(StrEnum):
    MACRO = "MACRO"
    INDUSTRY = "INDUSTRY"
    FUNDAMENTAL = "FUNDAMENTAL"
    MARKET_QUANT = "MARKET_QUANT"
    EVENT = "EVENT"
    PORTFOLIO_MANAGER = "PORTFOLIO_MANAGER"
    RISK_MANAGER = "RISK_MANAGER"
    DEVILS_ADVOCATE = "DEVILS_ADVOCATE"
    CIO = "CIO"
    REVIEW_LEARNING = "REVIEW_LEARNING"


class OpinionStance(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    MIXED = "MIXED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


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

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "statement", _require_text(self.statement, "observation statement")
        )
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
    risks: tuple[str, ...]
    schema_version: str = "v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "time_horizon", _require_text(self.time_horizon, "time horizon"))
        object.__setattr__(
            self, "schema_version", _require_text(self.schema_version, "schema version")
        )
        object.__setattr__(
            self, "assumptions", _normalize_text_items(self.assumptions, "assumption")
        )
        object.__setattr__(self, "unknowns", _normalize_text_items(self.unknowns, "unknown"))
        object.__setattr__(self, "risks", _normalize_text_items(self.risks, "risk"))
        if self.schema_version != "v1":
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "AgentOpinion requires the supported v1 schema",
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
