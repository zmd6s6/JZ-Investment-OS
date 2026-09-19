from uuid import UUID

from investment_os.application.thesis import (
    semantic_diff,
    thesis_content_hash,
    thesis_content_payload,
)
from investment_os.domain.enums import ThesisState
from investment_os.domain.thesis import (
    EvidenceBackedClaim,
    InvalidationCondition,
    PillarStatus,
    ThesisChangeReason,
    ThesisContent,
    ThesisPillar,
)

EVIDENCE_A = UUID("00000000-0000-0000-0000-000000000001")
EVIDENCE_B = UUID("00000000-0000-0000-0000-000000000002")
EVIDENCE_C = UUID("00000000-0000-0000-0000-000000000003")


def _claim(description: str, evidence_id: UUID) -> EvidenceBackedClaim:
    return EvidenceBackedClaim(description=description, evidence_ids=(evidence_id,))


def _content(
    *,
    state: ThesisState = ThesisState.VALID,
    summary: str = "Synthetic long-term Thesis",
    pillar: ThesisPillar | None = None,
    catalysts: tuple[EvidenceBackedClaim, ...] = (),
    monitoring: tuple[str, ...] = ("Review quarterly",),
) -> ThesisContent:
    return ThesisContent(
        state=state,
        long_term_summary=summary,
        pillars=(
            pillar
            or ThesisPillar(
                key="P1",
                claim=_claim("Revenue remains durable", EVIDENCE_A),
                status=PillarStatus.VALID,
            ),
        ),
        catalysts=catalysts,
        risks=(),
        invalidation_conditions=(
            InvalidationCondition(
                condition="Retention deteriorates",
                measurement="Net retention",
                threshold="below 90%",
                window="two quarters",
            ),
        ),
        monitoring_conditions=monitoring,
        change_reason=ThesisChangeReason.NEW_EVIDENCE,
    )


def test_identical_thesis_content_has_no_material_diff() -> None:
    previous = _content(catalysts=(_claim("Product adoption", EVIDENCE_B),))
    current = _content(catalysts=(_claim("Product adoption", EVIDENCE_B),))

    assert not semantic_diff(previous, current).is_material


def test_diff_identifies_changed_pillar_and_state_without_creating_a_version() -> None:
    previous = _content()
    current = _content(
        state=ThesisState.WEAKENING,
        pillar=ThesisPillar(
            key="P1",
            claim=_claim("Revenue has weakened", EVIDENCE_C),
            status=PillarStatus.AT_RISK,
        ),
    )

    diff = semantic_diff(previous, current)

    assert diff.is_material
    assert diff.state_changed
    assert diff.changed_pillar_keys == ("P1",)


def test_diff_treats_a_changed_long_term_summary_as_material() -> None:
    diff = semantic_diff(_content(), _content(summary="A changed synthetic long-term Thesis"))

    assert diff.is_material
    assert diff.summary_changed


def test_diff_is_stable_when_semantic_collections_are_reordered() -> None:
    first = _content(
        catalysts=(
            _claim("Second catalyst", EVIDENCE_B),
            _claim("First catalyst", EVIDENCE_C),
        ),
        monitoring=("Review quarterly", "Watch retention"),
    )
    reordered = _content(
        catalysts=(
            _claim("First catalyst", EVIDENCE_C),
            _claim("Second catalyst", EVIDENCE_B),
        ),
        monitoring=("Watch retention", "Review quarterly"),
    )

    assert not semantic_diff(first, reordered).is_material


def test_content_hash_is_stable_for_semantically_reordered_collections() -> None:
    first = _content(
        catalysts=(
            _claim("Second catalyst", EVIDENCE_B),
            _claim("First catalyst", EVIDENCE_C),
        ),
        monitoring=("Review quarterly", "Watch retention"),
    )
    reordered = _content(
        catalysts=(
            _claim("First catalyst", EVIDENCE_C),
            _claim("Second catalyst", EVIDENCE_B),
        ),
        monitoring=("Watch retention", "Review quarterly"),
    )

    assert thesis_content_hash(first) == thesis_content_hash(reordered)
    assert thesis_content_payload(first)["state"] == "VALID"


def test_content_hash_changes_when_the_summary_changes() -> None:
    assert thesis_content_hash(_content()) != thesis_content_hash(
        _content(summary="A changed synthetic long-term Thesis")
    )
