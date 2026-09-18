"""Deterministic Thesis comparison without a decision or execution path."""

import json
from dataclasses import dataclass
from hashlib import sha256

from investment_os.domain.thesis import EvidenceBackedClaim, InvalidationCondition, ThesisContent


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
