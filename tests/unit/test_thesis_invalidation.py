from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from investment_os.application.thesis import MetricObservation, evaluate_invalidation
from investment_os.domain.enums import Action, ThesisState
from investment_os.domain.thesis import (
    EvidenceBackedClaim,
    InvalidationCondition,
    PillarStatus,
    ThesisChangeReason,
    ThesisContent,
    ThesisPillar,
)
from investment_os.domain.values import UtcTimestamp

EVIDENCE_A = UUID("00000000-0000-0000-0000-000000000001")
EVIDENCE_B = UUID("00000000-0000-0000-0000-000000000002")
OBSERVED_AT = UtcTimestamp(datetime(2026, 9, 18, 20, 0, tzinfo=UTC))


def _content(*, window: str = "single observation") -> ThesisContent:
    return ThesisContent(
        state=ThesisState.VALID,
        long_term_summary="Synthetic long-term thesis",
        pillars=(
            ThesisPillar(
                key="durability",
                claim=EvidenceBackedClaim("Synthetic durable demand", (EVIDENCE_A,)),
                status=PillarStatus.VALID,
            ),
        ),
        catalysts=(),
        risks=(),
        invalidation_conditions=(
            InvalidationCondition(
                condition="Synthetic retention deterioration",
                measurement="net_retention_pct",
                threshold="below 90%",
                window=window,
            ),
        ),
        monitoring_conditions=("Review synthetic retention",),
        change_reason=ThesisChangeReason.NEW_EVIDENCE,
    )


def _observation(value: str) -> MetricObservation:
    return MetricObservation(
        measurement="net_retention_pct",
        value=Decimal(value),
        observed_at=OBSERVED_AT,
        evidence_ids=(EVIDENCE_B,),
    )


def test_invalidation_proposes_broken_content_and_non_decision_forced_review() -> None:
    original = _content()

    evaluation = evaluate_invalidation(original, (_observation("85"),))

    assert evaluation.triggered_conditions == original.invalidation_conditions
    assert evaluation.proposed_content is not None
    assert evaluation.proposed_content.state is ThesisState.BROKEN
    assert evaluation.proposed_content.change_reason is ThesisChangeReason.EVENT
    assert original.state is ThesisState.VALID
    assert EVIDENCE_B in evaluation.proposed_content.evidence_ids
    assert evaluation.forced_review_candidate is not None
    assert evaluation.forced_review_candidate.force_committee_review is True
    assert evaluation.forced_review_candidate.action_candidates == (Action.REDUCE, Action.EXIT)


def test_invalidation_threshold_boundary_does_not_trigger_for_strict_below() -> None:
    evaluation = evaluate_invalidation(_content(), (_observation("90"),))

    assert evaluation.triggered_conditions == ()
    assert evaluation.proposed_content is None
    assert evaluation.forced_review_candidate is None


def test_unsupported_free_text_window_fails_closed_without_a_broken_proposal() -> None:
    evaluation = evaluate_invalidation(_content(window="two quarters"), (_observation("85"),))

    assert evaluation.triggered_conditions == ()
    assert (
        evaluation.unsupported_conditions == _content(window="two quarters").invalidation_conditions
    )
    assert evaluation.proposed_content is None
    assert evaluation.forced_review_candidate is None
