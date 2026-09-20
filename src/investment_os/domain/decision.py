"""Immutable, evidence-first Decision Journal aggregate."""

import hashlib
import json
from dataclasses import dataclass, field
from string import hexdigits
from uuid import UUID, uuid4

from investment_os.domain.enums import (
    Action,
    BucketAction,
    DecisionState,
    RiskIntent,
)
from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.values import UtcTimestamp, Weight


def _text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise DomainError(DomainErrorCode.INVARIANT_VIOLATION, f"{field_name} must not be blank")
    return normalized


def _text_items(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    return tuple(_text(value, field_name) for value in values)


@dataclass(frozen=True, slots=True)
class DecisionClaim:
    """One human-readable Decision reason or risk with explicit Evidence provenance."""

    text: str
    evidence_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", _text(self.text, "Decision claim"))
        if not self.evidence_ids or len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "a Decision claim requires unique Evidence references",
            )


@dataclass(frozen=True, slots=True)
class DecisionPosition:
    """The complete Core/Tactical position representation at one Decision point."""

    total: Weight
    core: Weight
    tactical: Weight

    def __post_init__(self) -> None:
        if self.core.value + self.tactical.value != self.total.value:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "Decision Core plus Tactical weight must equal total weight",
            )


@dataclass(frozen=True, slots=True)
class InvestmentDecision:
    """A versioned Decision snapshot; it has no broker or execution authority."""

    instrument_id: UUID
    portfolio_id: UUID
    thesis_version_id: UUID
    policy_version_id: UUID
    strategy_version_id: UUID
    risk_assessment_id: UUID
    position_sizing_run_id: UUID
    action: Action
    confidence: Weight
    risk_intent: RiskIntent
    position_before: DecisionPosition
    position_after_proposed: DecisionPosition
    core_action: BucketAction
    tactical_action: BucketAction
    reasons: tuple[DecisionClaim, ...]
    risks: tuple[DecisionClaim, ...]
    watch_conditions: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    unknowns: tuple[str, ...]
    dissent: tuple[str, ...]
    next_review_at: UtcTimestamp
    input_snapshot_hash: str
    prompt_bundle_version: str
    formula_version: str
    committee_session_id: UUID | None = None
    state: DecisionState = DecisionState.DRAFT
    version: int = 1
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.version < 1:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "Decision version must be positive",
            )
        if not self.reasons:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "a Decision requires at least one evidence-backed reason",
            )
        object.__setattr__(
            self, "watch_conditions", _text_items(self.watch_conditions, "watch condition")
        )
        object.__setattr__(
            self,
            "invalidation_conditions",
            _text_items(self.invalidation_conditions, "invalidation condition"),
        )
        object.__setattr__(self, "unknowns", _text_items(self.unknowns, "unknown"))
        object.__setattr__(self, "dissent", _text_items(self.dissent, "dissent"))
        object.__setattr__(
            self,
            "prompt_bundle_version",
            _text(self.prompt_bundle_version, "prompt bundle version"),
        )
        object.__setattr__(self, "formula_version", _text(self.formula_version, "formula version"))
        _validate_hash(self.input_snapshot_hash)
        _validate_bucket_actions(self.action, self.core_action, self.tactical_action)

    @property
    def evidence_ids(self) -> tuple[UUID, ...]:
        """Stable de-duplicated Evidence snapshot used by this Decision."""

        return tuple(
            sorted(
                {
                    evidence_id
                    for claim in self.reasons + self.risks
                    for evidence_id in claim.evidence_ids
                },
                key=str,
            )
        )

    @property
    def content_hash(self) -> str:
        """Canonical identity for audit/replay without serializing mutable infrastructure state."""

        payload = {
            "instrument_id": str(self.instrument_id),
            "portfolio_id": str(self.portfolio_id),
            "thesis_version_id": str(self.thesis_version_id),
            "policy_version_id": str(self.policy_version_id),
            "strategy_version_id": str(self.strategy_version_id),
            "risk_assessment_id": str(self.risk_assessment_id),
            "position_sizing_run_id": str(self.position_sizing_run_id),
            "committee_session_id": str(self.committee_session_id)
            if self.committee_session_id
            else None,
            "action": self.action.value,
            "confidence": str(self.confidence.value),
            "risk_intent": self.risk_intent.value,
            "position_before": _position_payload(self.position_before),
            "position_after_proposed": _position_payload(self.position_after_proposed),
            "core_action": self.core_action.value,
            "tactical_action": self.tactical_action.value,
            "reasons": _claims_payload(self.reasons),
            "risks": _claims_payload(self.risks),
            "watch_conditions": self.watch_conditions,
            "invalidation_conditions": self.invalidation_conditions,
            "unknowns": self.unknowns,
            "dissent": self.dissent,
            "next_review_at": self.next_review_at.value.isoformat(),
            "input_snapshot_hash": self.input_snapshot_hash,
            "prompt_bundle_version": self.prompt_bundle_version,
            "formula_version": self.formula_version,
            "state": self.state.value,
            "version": self.version,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def _validate_hash(value: str) -> None:
    if len(value) != 64 or any(character not in hexdigits for character in value):
        raise DomainError(
            DomainErrorCode.INVARIANT_VIOLATION,
            "Decision input snapshot hash must be a 64-character hexadecimal digest",
        )


def _validate_bucket_actions(
    action: Action,
    core_action: BucketAction,
    tactical_action: BucketAction,
) -> None:
    bucket_actions = {core_action, tactical_action}
    if action in {Action.WATCH, Action.AVOID} and bucket_actions != {BucketAction.NONE}:
        raise DomainError(
            DomainErrorCode.INVARIANT_VIOLATION,
            "WATCH and AVOID Decisions cannot contain a hidden bucket action",
        )
    if action in {Action.BUY, Action.ADD} and not bucket_actions.intersection(
        {BucketAction.BUY, BucketAction.ADD}
    ):
        raise DomainError(
            DomainErrorCode.INVARIANT_VIOLATION,
            "BUY and ADD Decisions require an explicit Core or Tactical increase action",
        )
    if action in {Action.REDUCE, Action.EXIT} and not bucket_actions.intersection(
        {BucketAction.REDUCE, BucketAction.EXIT}
    ):
        raise DomainError(
            DomainErrorCode.INVARIANT_VIOLATION,
            "REDUCE and EXIT Decisions require an explicit Core or Tactical reduction action",
        )


def _position_payload(position: DecisionPosition) -> dict[str, str]:
    return {
        "total": str(position.total.value),
        "core": str(position.core.value),
        "tactical": str(position.tactical.value),
    }


def _claims_payload(claims: tuple[DecisionClaim, ...]) -> list[dict[str, object]]:
    return [
        {
            "text": claim.text,
            "evidence_ids": sorted(str(evidence_id) for evidence_id in claim.evidence_ids),
        }
        for claim in claims
    ]
