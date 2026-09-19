from uuid import UUID, uuid4

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
    ThesisVersion,
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


def test_thesis_version_enforces_first_and_successor_lineage() -> None:
    first = ThesisVersion(
        id=uuid4(),
        thesis_id=uuid4(),
        version=1,
        parent_version_id=None,
        content_hash="A" * 64,
        content=_content(),
    )
    successor = ThesisVersion(
        id=uuid4(),
        thesis_id=first.thesis_id,
        version=2,
        parent_version_id=first.id,
        content_hash="b" * 64,
        content=_content(),
    )

    assert first.content_hash == "a" * 64
    assert successor.parent_version_id == first.id


@pytest.mark.parametrize(
    ("version", "parent_version_id", "content_hash"),
    [
        (0, None, "a" * 64),
        (1, uuid4(), "a" * 64),
        (2, None, "a" * 64),
        (1, None, "not-a-sha256-digest"),
    ],
)
def test_thesis_version_rejects_invalid_lineage_or_content_hash(
    version: int,
    parent_version_id: UUID | None,
    content_hash: str,
) -> None:
    with pytest.raises(DomainError) as error:
        ThesisVersion(
            id=uuid4(),
            thesis_id=uuid4(),
            version=version,
            parent_version_id=parent_version_id,
            content_hash=content_hash,
            content=_content(),
        )

    assert error.value.code is DomainErrorCode.INVARIANT_VIOLATION
