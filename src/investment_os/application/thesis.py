"""Deterministic Thesis comparison without a decision or execution path."""

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from investment_os.domain.enums import Action, ThesisState
from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.thesis import (
    EvidenceBackedClaim,
    InvalidationCondition,
    ThesisChangeReason,
    ThesisContent,
)
from investment_os.domain.values import UtcTimestamp, exact_decimal

_THRESHOLD_PATTERN = re.compile(
    r"^(?P<operator><=|>=|<|>)\s*(?P<value>\d+(?:\.\d+)?)%?$|"
    r"^(?P<word>below|above)\s+(?P<word_value>\d+(?:\.\d+)?)%?$",
    re.IGNORECASE,
)
_SINGLE_OBSERVATION_WINDOWS = frozenset({"single observation", "single_observation"})


def _claim_key(claim: EvidenceBackedClaim) -> tuple[str, tuple[str, ...]]:
    return claim.description, tuple(sorted(str(evidence_id) for evidence_id in claim.evidence_ids))


def _condition_key(condition: InvalidationCondition) -> tuple[str, str, str, str]:
    return condition.condition, condition.measurement, condition.threshold, condition.window


def _claim_payload(claim: EvidenceBackedClaim) -> dict[str, object]:
    return {
        "description": claim.description,
        "evidence_ids": sorted(str(evidence_id) for evidence_id in claim.evidence_ids),
    }


def thesis_content_payload(content: ThesisContent) -> dict[str, object]:
    """Return a canonical JSON-compatible payload for immutable storage and hashing."""

    return {
        "state": content.state.value,
        "long_term_summary": content.long_term_summary,
        "pillars": [
            {
                "key": pillar.key,
                "claim": _claim_payload(pillar.claim),
                "status": pillar.status.value,
            }
            for pillar in sorted(content.pillars, key=lambda pillar: pillar.key)
        ],
        "catalysts": [_claim_payload(claim) for claim in sorted(content.catalysts, key=_claim_key)],
        "risks": [_claim_payload(claim) for claim in sorted(content.risks, key=_claim_key)],
        "invalidation_conditions": [
            {
                "condition": condition.condition,
                "measurement": condition.measurement,
                "threshold": condition.threshold,
                "window": condition.window,
            }
            for condition in sorted(content.invalidation_conditions, key=_condition_key)
        ],
        "monitoring_conditions": sorted(content.monitoring_conditions),
        "change_reason": content.change_reason.value,
    }


def thesis_content_hash(content: ThesisContent) -> str:
    canonical = json.dumps(
        thesis_content_payload(content),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ThesisSemanticDiff:
    state_changed: bool
    summary_changed: bool
    added_pillar_keys: tuple[str, ...]
    removed_pillar_keys: tuple[str, ...]
    changed_pillar_keys: tuple[str, ...]
    added_catalysts: tuple[EvidenceBackedClaim, ...]
    removed_catalysts: tuple[EvidenceBackedClaim, ...]
    added_risks: tuple[EvidenceBackedClaim, ...]
    removed_risks: tuple[EvidenceBackedClaim, ...]
    added_invalidation_conditions: tuple[InvalidationCondition, ...]
    removed_invalidation_conditions: tuple[InvalidationCondition, ...]
    added_monitoring_conditions: tuple[str, ...]
    removed_monitoring_conditions: tuple[str, ...]

    @property
    def is_material(self) -> bool:
        return any(
            (
                self.state_changed,
                self.summary_changed,
                self.added_pillar_keys,
                self.removed_pillar_keys,
                self.changed_pillar_keys,
                self.added_catalysts,
                self.removed_catalysts,
                self.added_risks,
                self.removed_risks,
                self.added_invalidation_conditions,
                self.removed_invalidation_conditions,
                self.added_monitoring_conditions,
                self.removed_monitoring_conditions,
            )
        )


def semantic_diff(previous: ThesisContent, current: ThesisContent) -> ThesisSemanticDiff:
    """Compare immutable Thesis payloads independent of collection input ordering."""

    previous_pillars = {pillar.key: pillar for pillar in previous.pillars}
    current_pillars = {pillar.key: pillar for pillar in current.pillars}
    shared_keys = previous_pillars.keys() & current_pillars.keys()

    previous_catalysts = frozenset(previous.catalysts)
    current_catalysts = frozenset(current.catalysts)
    previous_risks = frozenset(previous.risks)
    current_risks = frozenset(current.risks)
    previous_invalidations = frozenset(previous.invalidation_conditions)
    current_invalidations = frozenset(current.invalidation_conditions)
    previous_monitoring = frozenset(previous.monitoring_conditions)
    current_monitoring = frozenset(current.monitoring_conditions)

    return ThesisSemanticDiff(
        state_changed=previous.state is not current.state,
        summary_changed=previous.long_term_summary != current.long_term_summary,
        added_pillar_keys=tuple(sorted(current_pillars.keys() - previous_pillars.keys())),
        removed_pillar_keys=tuple(sorted(previous_pillars.keys() - current_pillars.keys())),
        changed_pillar_keys=tuple(
            sorted(key for key in shared_keys if previous_pillars[key] != current_pillars[key])
        ),
        added_catalysts=tuple(sorted(current_catalysts - previous_catalysts, key=_claim_key)),
        removed_catalysts=tuple(sorted(previous_catalysts - current_catalysts, key=_claim_key)),
        added_risks=tuple(sorted(current_risks - previous_risks, key=_claim_key)),
        removed_risks=tuple(sorted(previous_risks - current_risks, key=_claim_key)),
        added_invalidation_conditions=tuple(
            sorted(current_invalidations - previous_invalidations, key=_condition_key)
        ),
        removed_invalidation_conditions=tuple(
            sorted(previous_invalidations - current_invalidations, key=_condition_key)
        ),
        added_monitoring_conditions=tuple(sorted(current_monitoring - previous_monitoring)),
        removed_monitoring_conditions=tuple(sorted(previous_monitoring - current_monitoring)),
    )


@dataclass(frozen=True, slots=True)
class MetricObservation:
    """One evidence-backed, deterministic input to Thesis monitoring."""

    measurement: str
    value: Decimal
    observed_at: UtcTimestamp
    evidence_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        measurement = self.measurement.strip()
        if not measurement:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "a monitoring observation requires a measurement",
            )
        if not self.evidence_ids:
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "a monitoring observation requires Evidence references",
            )
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "a monitoring observation must not repeat Evidence references",
            )
        object.__setattr__(self, "measurement", measurement)
        object.__setattr__(self, "value", exact_decimal(self.value))


@dataclass(frozen=True, slots=True)
class ForcedReviewCandidate:
    """A non-decision escalation for a BROKEN Thesis; it cannot submit an order."""

    force_committee_review: bool
    action_candidates: tuple[Action, ...]
    evidence_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class ThesisInvalidationEvaluation:
    triggered_conditions: tuple[InvalidationCondition, ...]
    unsupported_conditions: tuple[InvalidationCondition, ...]
    proposed_content: ThesisContent | None
    forced_review_candidate: ForcedReviewCandidate | None


def _threshold_matches(threshold: str, value: Decimal) -> bool | None:
    """Evaluate the narrow, documented threshold grammar or fail closed with ``None``."""

    match = _THRESHOLD_PATTERN.fullmatch(threshold.strip())
    if match is None:
        return None
    operator = match.group("operator")
    if operator is None:
        operator = "<" if match.group("word").lower() == "below" else ">"
        raw_threshold = match.group("word_value")
    else:
        raw_threshold = match.group("value")
    if raw_threshold is None:
        return None
    threshold_value = Decimal(raw_threshold)
    return {
        "<": value < threshold_value,
        "<=": value <= threshold_value,
        ">": value > threshold_value,
        ">=": value >= threshold_value,
    }[operator]


def evaluate_invalidation(
    content: ThesisContent,
    observations: tuple[MetricObservation, ...],
) -> ThesisInvalidationEvaluation:
    """Propose one immutable BROKEN payload only for explicit, evidence-backed conditions.

    Only ``single observation`` conditions using the strict comparison grammar are executable in
    V1. All other free-text conditions remain visible as unsupported and cannot silently trigger
    a state change. The returned candidate is deliberately not a Decision, approval, or order.
    """

    supported_conditions = tuple(
        condition
        for condition in content.invalidation_conditions
        if condition.window.casefold() in _SINGLE_OBSERVATION_WINDOWS
    )
    unsupported_conditions = tuple(
        condition
        for condition in content.invalidation_conditions
        if condition not in supported_conditions
    )
    triggered: list[tuple[InvalidationCondition, MetricObservation]] = []
    for condition in sorted(supported_conditions, key=_condition_key):
        for observation in sorted(
            observations,
            key=lambda item: (
                item.observed_at.value,
                item.measurement,
                tuple(map(str, item.evidence_ids)),
            ),
        ):
            if observation.measurement != condition.measurement:
                continue
            matches = _threshold_matches(condition.threshold, observation.value)
            if matches is True:
                triggered.append((condition, observation))

    triggered_conditions = tuple(condition for condition, _ in triggered)
    if not triggered or content.state is ThesisState.BROKEN:
        return ThesisInvalidationEvaluation(
            triggered_conditions=triggered_conditions,
            unsupported_conditions=unsupported_conditions,
            proposed_content=None,
            forced_review_candidate=None,
        )

    event_evidence_ids = tuple(
        evidence_id for _, observation in triggered for evidence_id in observation.evidence_ids
    )
    unique_event_evidence_ids = tuple(dict.fromkeys(event_evidence_ids))
    invalidation_risks = tuple(
        EvidenceBackedClaim(
            description=f"Invalidation observed: {condition.condition}",
            evidence_ids=observation.evidence_ids,
        )
        for condition, observation in triggered
    )
    proposed_content = ThesisContent(
        state=ThesisState.BROKEN,
        long_term_summary=content.long_term_summary,
        pillars=content.pillars,
        catalysts=content.catalysts,
        risks=content.risks + invalidation_risks,
        invalidation_conditions=content.invalidation_conditions,
        monitoring_conditions=content.monitoring_conditions,
        change_reason=ThesisChangeReason.EVENT,
    )
    return ThesisInvalidationEvaluation(
        triggered_conditions=triggered_conditions,
        unsupported_conditions=unsupported_conditions,
        proposed_content=proposed_content,
        forced_review_candidate=ForcedReviewCandidate(
            force_committee_review=True,
            action_candidates=(Action.REDUCE, Action.EXIT),
            evidence_ids=unique_event_evidence_ids,
        ),
    )
