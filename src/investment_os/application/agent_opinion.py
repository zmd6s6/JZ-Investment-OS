"""Strict translation of untrusted structured Agent output into domain values."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.domain.agent import (
    AgentOpinion,
    AgentRole,
    EvidenceBackedObservation,
    OpinionStance,
)
from investment_os.domain.errors import DomainError
from investment_os.domain.values import Weight


class StrictAgentPayload(BaseModel):
    """External protocol base: allow only the documented structured fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AgentObservationPayload(StrictAgentPayload):
    statement: str = Field(min_length=1)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)

    @field_validator("evidence_ids")
    @classmethod
    def reject_repeated_evidence_ids(cls, evidence_ids: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("evidence_ids must not contain duplicates")
        return evidence_ids


class AgentOpinionPayload(StrictAgentPayload):
    """Versioned machine protocol; prose is never an accepted alternative representation."""

    schema_version: Literal["v1"]
    role: AgentRole
    instrument_id: UUID
    stance: OpinionStance
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    time_horizon: str = Field(min_length=1)
    observations: tuple[AgentObservationPayload, ...]
    assumptions: tuple[str, ...]
    unknowns: tuple[str, ...]
    risks: tuple[str, ...]

    @field_validator("confidence", mode="before")
    @classmethod
    def reject_binary_confidence(cls, value: object) -> object:
        if isinstance(value, (bool, float)):
            raise ValueError("confidence must be a decimal string or Decimal, never binary float")
        return value

    def to_domain(self) -> AgentOpinion:
        return AgentOpinion(
            role=self.role,
            instrument_id=self.instrument_id,
            stance=self.stance,
            confidence=Weight(self.confidence),
            time_horizon=self.time_horizon,
            observations=tuple(
                EvidenceBackedObservation(
                    statement=observation.statement,
                    evidence_ids=observation.evidence_ids,
                )
                for observation in self.observations
            ),
            assumptions=self.assumptions,
            unknowns=self.unknowns,
            risks=self.risks,
            schema_version=self.schema_version,
        )


def parse_agent_opinion(payload: object) -> AgentOpinion:
    """Fail closed while exposing only sanitized validation details to outer adapters."""

    try:
        return AgentOpinionPayload.model_validate(payload).to_domain()
    except (DomainError, ValidationError) as exc:
        errors = exc.errors() if isinstance(exc, ValidationError) else []
        raise ApplicationError(
            ApplicationErrorCode.AGENT_OPINION_INVALID,
            "AgentOpinion payload did not satisfy the v1 structured protocol",
            details={
                "errors": [
                    {
                        "location": ".".join(str(part) for part in error["loc"]),
                        "type": str(error["type"]),
                        "message": str(error["msg"]),
                    }
                    for error in errors
                ]
            },
        ) from exc
