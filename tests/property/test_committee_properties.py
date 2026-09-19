"""Property coverage for deterministic, finite PR-05 research boundaries."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from hypothesis import given
from hypothesis import strategies as st

from investment_os.application.analysis_context import AnalysisEvidence, freeze_analysis_context
from investment_os.application.committee import detect_stance_conflicts
from investment_os.domain.agent import (
    AgentOpinion,
    AgentRole,
    EvidenceBackedObservation,
    OpinionStance,
)
from investment_os.domain.values import UtcTimestamp, Weight

NOW = datetime(2026, 9, 19, 0, 0, tzinfo=UTC)
INSTRUMENT_ID = UUID("00000000-0000-0000-0000-000000000001")
EVIDENCE_IDS = (
    UUID("00000000-0000-0000-0000-000000000011"),
    UUID("00000000-0000-0000-0000-000000000012"),
    UUID("00000000-0000-0000-0000-000000000013"),
)


def _evidence() -> tuple[AnalysisEvidence, ...]:
    return (
        AnalysisEvidence(EVIDENCE_IDS[0], "a" * 64, UtcTimestamp(NOW)),
        AnalysisEvidence(EVIDENCE_IDS[1], "b" * 64, UtcTimestamp(NOW)),
        AnalysisEvidence(EVIDENCE_IDS[2], "c" * 64, UtcTimestamp(NOW + timedelta(seconds=1))),
    )


@given(order=st.permutations((0, 1, 2)))
def test_analysis_context_hash_is_invariant_to_evidence_order(
    order: tuple[int, int, int],
) -> None:
    evidence = _evidence()

    baseline = freeze_analysis_context(INSTRUMENT_ID, as_of=NOW, evidence=evidence)
    reordered = freeze_analysis_context(
        INSTRUMENT_ID,
        as_of=NOW,
        evidence=tuple(evidence[index] for index in order),
    )

    assert reordered.input_snapshot_hash == baseline.input_snapshot_hash
    assert reordered.evidence == baseline.evidence
    assert reordered.visible_evidence_ids == frozenset(EVIDENCE_IDS[:2])


def _opinion(role: AgentRole, stance: OpinionStance) -> AgentOpinion:
    return AgentOpinion(
        role=role,
        instrument_id=INSTRUMENT_ID,
        stance=stance,
        confidence=Weight(Decimal("0.5")),
        time_horizon="synthetic property horizon",
        observations=(EvidenceBackedObservation("Synthetic fact", (EVIDENCE_IDS[0],)),),
        assumptions=(),
        unknowns=(),
        risks=(),
    )


@given(order=st.permutations((0, 1, 2)))
def test_conflict_detection_is_invariant_to_independent_opinion_arrival_order(
    order: tuple[int, int, int],
) -> None:
    opinions = (
        _opinion(AgentRole.MACRO, OpinionStance.POSITIVE),
        _opinion(AgentRole.INDUSTRY, OpinionStance.MIXED),
        _opinion(AgentRole.FUNDAMENTAL, OpinionStance.NEGATIVE),
    )

    baseline = detect_stance_conflicts(opinions)
    reordered = detect_stance_conflicts(tuple(opinions[index] for index in order))

    assert reordered == baseline
    assert baseline[0].roles == (AgentRole.FUNDAMENTAL, AgentRole.MACRO)
