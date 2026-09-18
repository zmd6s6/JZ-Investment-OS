from uuid import uuid4

import pytest

from investment_os.domain.enums import ThesisState
from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.thesis import (
    EvidenceBackedClaim,
    InvalidationCondition,
    PillarStatus,
    ThesisChangeReason,
    ThesisContent,
    ThesisPillar,
)


def _claim(description: str = "Durable revenue growth") -> EvidenceBackedClaim:
    return EvidenceBackedClaim(description=description, evidence_ids=(uuid4(),))


def _content(*, state: ThesisState = ThesisState.VALID) -> ThesisContent:
    invalidation = (
        InvalidationCondition(
            condition="Retention deteriorates",
            measurement="Net retention",
            threshold="below 90%",
            window="two quarters",
        ),
    )
    return ThesisContent(
        state=state,
        long_term_summary="A synthetic long-term thesis.",
        pillars=(ThesisPillar(key="P1", claim=_claim(), status=PillarStatus.VALID),),
        catalysts=(_claim("New product adoption"),),
        risks=(_claim("Competition intensifies"),),
        invalidation_conditions=invalidation,
        monitoring_conditions=("Review retention quarterly",),
        change_reason=ThesisChangeReason.NEW_EVIDENCE,
    )


def test_thesis_content_preserves_deduplicated_evidence_provenance() -> None:
    content = _content()

    assert len(content.evidence_ids) == 3
    assert content.pillars[0].claim.evidence_ids[0] in content.evidence_ids


def test_thesis_content_rejects_repeated_pillar_keys() -> None:
    claim = _claim()

    with pytest.raises(DomainError) as error:
        ThesisContent(
            state=ThesisState.VALID,
            long_term_summary="Synthetic thesis",
            pillars=(
                ThesisPillar(key="P1", claim=claim, status=PillarStatus.VALID),
                ThesisPillar(key="P1", claim=_claim(), status=PillarStatus.AT_RISK),
            ),
            catalysts=(),
            risks=(),
            invalidation_conditions=(),
            monitoring_conditions=(),
            change_reason=ThesisChangeReason.NEW_EVIDENCE,
        )

    assert error.value.code is DomainErrorCode.INVARIANT_VIOLATION


def test_broken_thesis_requires_an_explicit_invalidation_condition() -> None:
    with pytest.raises(DomainError, match="invalidation condition"):
        ThesisContent(
            state=ThesisState.BROKEN,
            long_term_summary="Synthetic broken thesis",
            pillars=(ThesisPillar(key="P1", claim=_claim(), status=PillarStatus.INVALID),),
            catalysts=(),
            risks=(),
            invalidation_conditions=(),
            monitoring_conditions=(),
            change_reason=ThesisChangeReason.EVENT,
        )
