from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from investment_os.application.analysis_context import (
    AnalysisEvidence,
    freeze_analysis_context,
    require_context_evidence,
)
from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.domain.agent import (
    AgentOpinion,
    AgentRole,
    EvidenceBackedObservation,
    OpinionStance,
)
from investment_os.domain.values import UtcTimestamp, Weight

NOW = datetime(2026, 9, 19, 0, 0, tzinfo=UTC)


def _evidence(
    *, evidence_id: object | None = None, available_at: datetime = NOW
) -> AnalysisEvidence:
    return AnalysisEvidence(
        evidence_id=evidence_id if evidence_id is not None else uuid4(),
        content_hash="a" * 64,
        available_at=UtcTimestamp(available_at),
    )


def test_context_is_stable_and_excludes_future_available_evidence() -> None:
    instrument_id = uuid4()
    visible = _evidence()
    future = _evidence(available_at=NOW + timedelta(seconds=1))

    first = freeze_analysis_context(instrument_id, as_of=NOW, evidence=(future, visible))
    second = freeze_analysis_context(instrument_id, as_of=NOW, evidence=(visible, future))

    assert first.visible_evidence_ids == frozenset({visible.evidence_id})
    assert first.input_snapshot_hash == second.input_snapshot_hash


def test_context_rejects_duplicate_visible_evidence_ids() -> None:
    duplicate_id = uuid4()

    with pytest.raises(ApplicationError) as error:
        freeze_analysis_context(
            uuid4(),
            as_of=NOW,
            evidence=(_evidence(evidence_id=duplicate_id), _evidence(evidence_id=duplicate_id)),
        )

    assert error.value.code is ApplicationErrorCode.AGENT_OPINION_EVIDENCE_UNAVAILABLE


@pytest.mark.parametrize("content_hash", ("not-a-hash", "A" * 64, "a" * 63))
def test_context_rejects_evidence_without_a_canonical_content_hash(content_hash: str) -> None:
    with pytest.raises(ApplicationError) as error:
        AnalysisEvidence(
            evidence_id=uuid4(),
            content_hash=content_hash,
            available_at=UtcTimestamp(NOW),
        )

    assert error.value.code is ApplicationErrorCode.AGENT_OPINION_EVIDENCE_UNAVAILABLE


def test_opinion_must_reference_evidence_visible_in_its_frozen_context() -> None:
    visible = _evidence()
    context = freeze_analysis_context(uuid4(), as_of=NOW, evidence=(visible,))
    opinion = AgentOpinion(
        role=AgentRole.EVENT,
        instrument_id=context.instrument_id,
        stance=OpinionStance.NEGATIVE,
        confidence=Weight(Decimal("0.4")),
        time_horizon="synthetic event window",
        observations=(EvidenceBackedObservation("Synthetic fact", (uuid4(),)),),
        assumptions=(),
        unknowns=(),
        risks=(),
    )

    with pytest.raises(ApplicationError) as error:
        require_context_evidence(opinion, context)

    assert error.value.code is ApplicationErrorCode.AGENT_OPINION_EVIDENCE_UNAVAILABLE
