"""Read saved team observations for explicit human drafting, never write a Thesis."""

import json
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from investment_os.application.analysis_research import AnalysisResearchReader
from investment_os.application.analysis_run import AnalysisRunService
from investment_os.application.analysis_thesis import AnalysisThesisInput
from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.domain.agent import AgentRole


class ReviewDto(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TeamThesisSource(ReviewDto):
    analysis_run_id: UUID
    suggestion_ids: tuple[Annotated[str, StringConstraints(max_length=100)], ...] = Field(
        default=(), max_length=20
    )
    impact_ids: tuple[Annotated[str, StringConstraints(min_length=1, max_length=100)], ...] = Field(
        default=(), max_length=20
    )

    @model_validator(mode="after")
    def unique(self) -> Self:
        if not 1 <= len(self.suggestion_ids) + len(self.impact_ids) <= 20:
            raise ValueError("select between one and twenty review items")
        if len(set(self.suggestion_ids)) != len(self.suggestion_ids) or len(
            set(self.impact_ids)
        ) != len(self.impact_ids):
            raise ValueError("review suggestions must be unique")
        return self


class TeamThesisProvenance(ReviewDto):
    analysis_run_id: UUID
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    suggestion_ids: tuple[str, ...]
    opinion_ids: tuple[UUID, ...]
    impact_ids: tuple[str, ...] = ()


class TeamThesisSuggestion(ReviewDto):
    id: str
    opinion_id: UUID
    role: AgentRole
    stage: str
    claim: Annotated[str, StringConstraints(min_length=1, max_length=3000)]
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=50)


class TeamThesisReview(ReviewDto):
    schema_version: Literal["1.0"] = "1.0"
    analysis_run_id: UUID
    instrument_id: UUID
    as_of: str
    input_hash: str
    base_version_id: UUID | None
    suggestions: tuple[TeamThesisSuggestion, ...]
    unknowns: tuple[str, ...]
    risk_gate: Literal["PASS", "VETO", "UNKNOWN"]
    limitations: tuple[str, ...]
    impacts: tuple["TeamThesisImpact", ...] = ()


class SavedImpact(ReviewDto):
    pillar_key: Annotated[str, StringConstraints(min_length=1)]
    impact: Literal["STRENGTHEN", "WEAKEN", "BREAK", "NONE"]
    reason: Annotated[str, StringConstraints(min_length=1)]
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=50)


class TeamThesisImpact(SavedImpact):
    id: str
    opinion_id: UUID
    role: AgentRole
    stage: str
    baseline_status: Literal["MATCHED", "UNMATCHED", "NO_BASELINE"]
    baseline_claim: str | None = None
    baseline_pillar_status: str | None = None


class SavedObservation(ReviewDto):
    model_config = ConfigDict(extra="ignore", frozen=True)
    claim: str
    evidence_ids: tuple[UUID, ...]


class SavedOpinion(ReviewDto):
    # This is a read projection, not a relaxed runtime AgentOpinion parser.
    model_config = ConfigDict(extra="ignore", frozen=True)
    role: AgentRole
    stage: Literal["ROUND_1", "ROUND_2", "PORTFOLIO", "RISK"]
    status: str
    error_code: str | None
    opinion_id: UUID
    unknowns: tuple[str, ...]
    observations: tuple[SavedObservation, ...]
    thesis_impacts: tuple[SavedImpact, ...] = ()


def invalid_review() -> ApplicationError:
    return ApplicationError(
        ApplicationErrorCode.THESIS_REVIEW_UNAVAILABLE,
        "saved team research or its frozen Thesis baseline cannot be verified",
    )


class TeamThesisReviewService:
    def __init__(self, runs: AnalysisRunService, research: AnalysisResearchReader):
        self._runs, self._research = runs, research

    async def read(self, run_id: UUID) -> TeamThesisReview:
        run = await self._runs.get(run_id)
        records = await self._research.read(run_id)
        try:
            snapshot = run.payload["input_snapshot"]
            thesis_payload = dict(snapshot["thesis"])
            effective_state = thesis_payload.pop("effective_state")
            thesis = AnalysisThesisInput.model_validate_json(json.dumps(thesis_payload))
            if (
                run.status != "SUCCEEDED"
                or records.status != "RECORDED"
                or records.run_id != run.id
                or records.input_hash != snapshot["input_hash"]
                or thesis.instrument_id != run.instrument_id
                or thesis.as_of != run.as_of
                or effective_state != thesis.state.value
            ):
                raise ValueError("research is incomplete or does not match the input")
            visible = {str(e["evidence_id"]) for e in snapshot["evidence"]}
            latest: dict[AgentRole, SavedOpinion] = {}
            for raw_agent in records.agents:
                agent = SavedOpinion.model_validate(raw_agent)
                role = agent.role
                # The second round supersedes that role's first-round drafting input.
                if role not in latest or agent.stage == "ROUND_2":
                    latest[role] = agent
            suggestions: list[TeamThesisSuggestion] = []
            unknowns: list[str] = []
            omitted = 0
            impacts: list[TeamThesisImpact] = []
            omitted_impacts = 0
            pillars = {p.key: p for p in thesis.version.content.pillars} if thesis.version else {}
            for role, agent in latest.items():
                unknowns.extend(f"{role}: {item}" for item in agent.unknowns)
                if agent.status != "SUCCEEDED" or agent.error_code is not None:
                    unknowns.append(f"{role}: INSUFFICIENT_DATA")
                    continue
                for index, impact in enumerate(agent.thesis_impacts):
                    if not {str(e) for e in impact.evidence_ids}.issubset(visible):
                        raise ValueError("impact exceeds this run's evidence boundary")
                    if len(impacts) < 100:
                        pillar = pillars.get(impact.pillar_key)
                        impacts.append(
                            TeamThesisImpact(
                                **impact.model_dump(),
                                id=f"{agent.opinion_id}:impact:{index}",
                                opinion_id=agent.opinion_id,
                                role=role,
                                stage=agent.stage,
                                baseline_status="MATCHED"
                                if pillar
                                else "UNMATCHED"
                                if thesis.version
                                else "NO_BASELINE",
                                baseline_claim=pillar.claim.description if pillar else None,
                                baseline_pillar_status=pillar.status.value if pillar else None,
                            )
                        )
                    else:
                        omitted_impacts += 1
                for index, raw in enumerate(agent.observations):
                    suggestion = TeamThesisSuggestion(
                        id=f"{agent.opinion_id}:{index}",
                        opinion_id=agent.opinion_id,
                        role=role,
                        stage=agent.stage,
                        claim=raw.claim,
                        evidence_ids=raw.evidence_ids,
                    )
                    if not {str(e) for e in suggestion.evidence_ids}.issubset(visible):
                        raise ValueError("observation exceeds this run's evidence boundary")
                    if len(suggestions) < 100:
                        suggestions.append(suggestion)
                    else:
                        omitted += 1
            return TeamThesisReview(
                analysis_run_id=run.id,
                instrument_id=run.instrument_id,
                as_of=run.as_of.isoformat(),
                input_hash=records.input_hash,
                base_version_id=thesis.version.id if thesis.version else None,
                suggestions=tuple(suggestions),
                impacts=tuple(impacts),
                unknowns=tuple(dict.fromkeys(unknowns)),
                risk_gate=records.risk["gate"] if records.risk else "UNKNOWN",
                limitations=(
                    "HUMAN_REVIEW_REQUIRED_NO_AUTOMATIC_STATE_CHANGE",
                    "OBSERVATIONS_ARE_UNTRUSTED_MODEL_JUDGMENTS",
                    f"ADDITIONAL_OBSERVATIONS_NOT_SHOWN:{omitted}",
                    f"ADDITIONAL_IMPACTS_NOT_SHOWN:{omitted_impacts}",
                ),
            )
        except (ValueError, KeyError, TypeError):
            raise invalid_review() from None
