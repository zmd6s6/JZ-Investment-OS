"""Strict translation of the Master-Spec AgentOpinion wire contract."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.domain.agent import (
    AgentOpinion,
    AgentRisk,
    AgentRole,
    EvidenceBackedObservation,
    InvalidationCondition,
    ObservationMateriality,
    OpinionStance,
    RiskSeverity,
    ThesisImpact,
    ThesisImpactKind,
)
from investment_os.domain.errors import DomainError
from investment_os.domain.values import UtcTimestamp, Weight


class StrictAgentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AgentObservationPayload(StrictAgentPayload):
    claim: str = Field(min_length=1)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    materiality: ObservationMateriality


class ThesisImpactPayload(StrictAgentPayload):
    pillar_key: str = Field(min_length=1)
    impact: ThesisImpactKind
    reason: str = Field(min_length=1)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)


class AgentRiskPayload(StrictAgentPayload):
    code: str = Field(min_length=1)
    severity: RiskSeverity
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)


class InvalidationConditionPayload(StrictAgentPayload):
    condition: str = Field(min_length=1)
    observable: str = Field(min_length=1)


class AgentOpinionPayload(StrictAgentPayload):
    """Master Spec §6.2; free-form or legacy protocol fields fail closed."""

    schema_version: Literal["1.0"]
    agent_role: AgentRole
    instrument_id: UUID
    as_of: datetime
    stance: OpinionStance
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    time_horizon: Literal["DAYS", "WEEKS", "MONTHS", "QUARTERS", "YEARS"]
    observations: tuple[AgentObservationPayload, ...]
    thesis_impacts: tuple[ThesisImpactPayload, ...]
    assumptions: tuple[str, ...]
    risks: tuple[AgentRiskPayload, ...]
    invalidation_conditions: tuple[InvalidationConditionPayload, ...]
    unknowns: tuple[str, ...]
    requested_followups: tuple[str, ...]

    @field_validator("confidence", mode="before")
    @classmethod
    def reject_binary_confidence(cls, value: object) -> object:
        if isinstance(value, (bool, float)):
            raise ValueError("confidence must be a decimal string or Decimal, never binary float")
        return value

    def to_domain(self) -> AgentOpinion:
        return AgentOpinion(
            role=self.agent_role,
            instrument_id=self.instrument_id,
            as_of=UtcTimestamp(self.as_of),
            stance=self.stance,
            confidence=Weight(self.confidence),
            time_horizon=self.time_horizon,
            observations=tuple(
                EvidenceBackedObservation(item.claim, item.evidence_ids, item.materiality)
                for item in self.observations
            ),
            thesis_impacts=tuple(
                ThesisImpact(item.pillar_key, item.impact, item.reason, item.evidence_ids)
                for item in self.thesis_impacts
            ),
            assumptions=self.assumptions,
            risks=tuple(
                AgentRisk(item.code, item.severity, item.evidence_ids) for item in self.risks
            ),
            invalidation_conditions=tuple(
                InvalidationCondition(item.condition, item.observable)
                for item in self.invalidation_conditions
            ),
            unknowns=self.unknowns,
            requested_followups=self.requested_followups,
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
            "AgentOpinion payload did not satisfy the 1.0 structured protocol",
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
