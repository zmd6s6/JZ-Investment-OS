"""S1/S2 research fixtures that deliberately stop before the PR-07 CIO Action gate."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from investment_os.application.analysis_context import (
    AnalysisEvidence,
    freeze_analysis_context,
    require_context_evidence,
)
from investment_os.application.committee import detect_stance_conflicts, plan_round_two
from investment_os.domain.agent import (
    AgentOpinion,
    AgentRole,
    EvidenceBackedObservation,
    OpinionStance,
)
from investment_os.domain.values import UtcTimestamp, Weight

NOW = datetime(2026, 9, 20, 0, 0, tzinfo=UTC)


def _opinion(
    *,
    role: AgentRole,
    stance: OpinionStance,
    instrument_id: UUID,
    evidence_id: UUID,
) -> AgentOpinion:
    if stance is OpinionStance.INSUFFICIENT_DATA:
        return AgentOpinion(
            role=role,
            instrument_id=instrument_id,
            stance=stance,
            confidence=Weight(Decimal("0")),
            time_horizon="synthetic research horizon",
            observations=(),
            assumptions=(),
            unknowns=("Synthetic research input is insufficient",),
            risks=(),
        )
    return AgentOpinion(
        role=role,
        instrument_id=instrument_id,
        stance=stance,
        confidence=Weight(Decimal("0.5")),
        time_horizon="synthetic research horizon",
        observations=(
            EvidenceBackedObservation(
                "Synthetic evidence-backed research observation", (evidence_id,)
            ),
        ),
        assumptions=(),
        unknowns=(),
        risks=(),
    )


@pytest.mark.parametrize(
    ("scenario", "stances", "expected_round_two_roles"),
    (
        pytest.param(
            "S1",
            (
                (AgentRole.INDUSTRY, OpinionStance.POSITIVE),
                (AgentRole.FUNDAMENTAL, OpinionStance.POSITIVE),
                (AgentRole.MARKET_QUANT, OpinionStance.NEGATIVE),
            ),
            (
                AgentRole.DEVILS_ADVOCATE,
                AgentRole.FUNDAMENTAL,
                AgentRole.INDUSTRY,
                AgentRole.MARKET_QUANT,
            ),
            id="positive-investment-research-with-weak-timing",
        ),
        pytest.param(
            "S2",
            (
                (AgentRole.INDUSTRY, OpinionStance.INSUFFICIENT_DATA),
                (AgentRole.FUNDAMENTAL, OpinionStance.INSUFFICIENT_DATA),
                (AgentRole.MARKET_QUANT, OpinionStance.POSITIVE),
            ),
            (AgentRole.DEVILS_ADVOCATE,),
            id="strong-timing-with-insufficient-investment-research",
        ),
    ),
)
def test_s1_s2_research_inputs_are_evidence_bound_and_stop_before_cio_action(
    scenario: str,
    stances: tuple[tuple[AgentRole, OpinionStance], ...],
    expected_round_two_roles: tuple[AgentRole, ...],
) -> None:
    """Keep PR-05 scenario fixtures in the research/committee layer only.

    PR-07 owns the CIO's final `WATCH`/`AVOID` Action assertions.  This fixture demonstrates
    the factual preconditions without importing a Decision or manufacturing an Action.
    """

    instrument_id = uuid4()
    evidence_id = uuid4()
    context = freeze_analysis_context(
        instrument_id,
        as_of=NOW,
        evidence=(
            AnalysisEvidence(
                evidence_id=evidence_id,
                content_hash="a" * 64,
                available_at=UtcTimestamp(NOW),
            ),
        ),
    )
    opinions = tuple(
        _opinion(
            role=role,
            stance=stance,
            instrument_id=instrument_id,
            evidence_id=evidence_id,
        )
        for role, stance in stances
    )

    for opinion in opinions:
        require_context_evidence(opinion, context)

    # The polarity is intentionally represented as structured committee input, not translated
    # into a final recommendation in this stage.
    conflicts = detect_stance_conflicts(opinions)
    round_two = plan_round_two(conflicts)

    assert bool(conflicts) is (scenario == "S1")
    assert AgentRole.CIO not in {opinion.role for opinion in opinions}
    assert round_two.roles == expected_round_two_roles
