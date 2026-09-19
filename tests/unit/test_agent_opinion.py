from decimal import Decimal
from uuid import uuid4

import pytest

from investment_os.domain.agent import (
    AgentOpinion,
    AgentRole,
    EvidenceBackedObservation,
    OpinionStance,
)
from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.values import Weight


def _observation() -> EvidenceBackedObservation:
    return EvidenceBackedObservation(
        statement="Synthetic revenue growth decelerated.",
        evidence_ids=(uuid4(),),
    )


def test_agent_opinion_preserves_evidence_backed_facts_and_separate_unknowns() -> None:
    opinion = AgentOpinion(
        role=AgentRole.FUNDAMENTAL,
        instrument_id=uuid4(),
        stance=OpinionStance.NEGATIVE,
        confidence=Weight(Decimal("0.6")),
        time_horizon="next two quarters",
        observations=(_observation(),),
        assumptions=("Synthetic demand data is representative.",),
        unknowns=("The next quarter has not been reported.",),
        risks=("Competition could increase further.",),
    )

    assert opinion.schema_version == "v1"
    assert opinion.observations[0].evidence_ids
    assert opinion.unknowns == ("The next quarter has not been reported.",)


@pytest.mark.parametrize(
    "observation",
    [
        EvidenceBackedObservation(statement="Synthetic fact", evidence_ids=(uuid4(),)),
    ],
)
def test_substantive_opinion_requires_evidence_backed_observation(
    observation: EvidenceBackedObservation,
) -> None:
    with pytest.raises(DomainError) as error:
        AgentOpinion(
            role=AgentRole.MACRO,
            instrument_id=uuid4(),
            stance=OpinionStance.MIXED,
            confidence=Weight(Decimal("0.5")),
            time_horizon="one month",
            observations=(),
            assumptions=(),
            unknowns=("Synthetic unknown",),
            risks=(),
        )

    assert observation.evidence_ids
    assert error.value.code is DomainErrorCode.INVARIANT_VIOLATION


def test_observation_rejects_empty_or_repeated_evidence_references() -> None:
    evidence_id = uuid4()

    with pytest.raises(DomainError, match="at least one Evidence"):
        EvidenceBackedObservation(statement="Synthetic fact", evidence_ids=())
    with pytest.raises(DomainError, match="must not repeat"):
        EvidenceBackedObservation(
            statement="Synthetic fact", evidence_ids=(evidence_id, evidence_id)
        )


def test_insufficient_data_is_an_explicit_zero_confidence_failure_outcome() -> None:
    opinion = AgentOpinion(
        role=AgentRole.EVENT,
        instrument_id=uuid4(),
        stance=OpinionStance.INSUFFICIENT_DATA,
        confidence=Weight(Decimal("0")),
        time_horizon="current event window",
        observations=(),
        assumptions=(),
        unknowns=("The synthetic provider timed out.",),
        risks=(),
    )

    assert opinion.stance is OpinionStance.INSUFFICIENT_DATA


@pytest.mark.parametrize(
    ("confidence", "observations"),
    [
        (Decimal("0.1"), ()),
        (Decimal("0"), (_observation(),)),
    ],
)
def test_insufficient_data_rejects_confidence_or_factual_claims(
    confidence: Decimal,
    observations: tuple[EvidenceBackedObservation, ...],
) -> None:
    with pytest.raises(DomainError) as error:
        AgentOpinion(
            role=AgentRole.EVENT,
            instrument_id=uuid4(),
            stance=OpinionStance.INSUFFICIENT_DATA,
            confidence=Weight(confidence),
            time_horizon="current event window",
            observations=observations,
            assumptions=(),
            unknowns=("The synthetic provider timed out.",),
            risks=(),
        )

    assert error.value.code is DomainErrorCode.INVARIANT_VIOLATION
