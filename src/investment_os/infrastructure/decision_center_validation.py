"""Strict reconstruction of frozen domain inputs before authorizing human actions."""

import json
from decimal import Decimal

from pydantic import TypeAdapter

from investment_os.application.policy_schema import InvestmentPolicySchema
from investment_os.application.thesis import thesis_content_hash
from investment_os.domain.agent import AgentOpinion
from investment_os.domain.sizing import (
    PositionSizingResult,
    SizingFormula,
    SizingRequest,
    size_position,
)
from investment_os.domain.thesis import ThesisContent
from investment_os.infrastructure.persistence.models import (
    AgentOpinionRecord,
    AgentRunRecord,
    InvestmentDecisionRecord,
    InvestmentPolicyVersionRecord,
    PositionSizingRunRecord,
    RiskAssessmentRecord,
    ThesisVersionRecord,
)


def thesis_content(record: ThesisVersionRecord) -> ThesisContent:
    content = TypeAdapter(ThesisContent).validate_python(
        {
            "state": record.thesis_state,
            "long_term_summary": record.summary,
            "pillars": record.pillars_json,
            "catalysts": record.catalysts_json,
            "risks": record.risks_json,
            "invalidation_conditions": record.invalidation_conditions_json,
            "monitoring_conditions": record.monitoring_conditions_json,
            "change_reason": record.change_reason,
        }
    )
    if thesis_content_hash(content) != record.content_hash:
        raise ValueError("THESIS_CONTENT_HASH_MISMATCH")
    return content


def sizing_request(
    sizing: PositionSizingRunRecord,
    decision: InvestmentDecisionRecord,
    policy: InvestmentPolicyVersionRecord,
    risk: RiskAssessmentRecord,
    thesis: ThesisVersionRecord,
) -> SizingRequest:
    def require_exact(value: object) -> None:
        if isinstance(value, (float, bool)):
            raise ValueError("SIZING_REQUIRES_EXACT_NUMERIC_INPUTS")
        if isinstance(value, dict):
            for item in value.values():
                require_exact(item)
        elif isinstance(value, list):
            for item in value:
                require_exact(item)

    require_exact(sizing.input_json["request"])
    require_exact(sizing.input_json["formula"])
    require_exact(sizing.output_json)
    request = TypeAdapter(SizingRequest).validate_python(sizing.input_json["request"])
    formula = TypeAdapter(SizingFormula).validate_python(sizing.input_json["formula"])
    output = TypeAdapter(PositionSizingResult).validate_python(sizing.output_json)
    computed = size_position(formula, request)
    schema = InvestmentPolicySchema.model_validate_json(json.dumps(policy.config_json))
    persisted_flags = [*risk.hard_flags_json, *risk.soft_flags_json]
    if (
        computed != output
        or computed.input_hash != sizing.input_hash
        or formula.version != sizing.formula_version
        or request.policy != schema.to_domain().position
        or request.action.value != decision.action
        or request.risk_intent.value != decision.risk_intent
        or request.thesis_state.value != thesis.thesis_state
        or request.reference_price != Decimal(str(sizing.input_json["reference_price"]))
        or request.risk_assessment.id != risk.id
        or request.risk_assessment.expires_at.value != risk.expires_at
        or request.risk_assessment.content_hash != risk.content_hash
        or request.risk_assessment.as_of.value > request.as_of.value
        or request.as_of.value > decision.created_at
        or len(request.risk_assessment.flags) != len(persisted_flags)
        or {
            (
                flag.code,
                flag.kind.value,
                flag.severity.value,
                flag.release_condition,
                frozenset(str(identifier) for identifier in flag.evidence_ids),
            )
            for flag in request.risk_assessment.flags
        }
        != {
            (
                flag["code"],
                flag["kind"],
                flag["severity"],
                flag["release_condition"],
                frozenset(flag["evidence_ids"]),
            )
            for flag in persisted_flags
        }
        or output.target_weight.value
        != Decimal(str(decision.position_after_proposed_json[request.bucket.value.lower()]))
        or request.current_bucket_weight.value
        != Decimal(str(decision.position_before_json[request.bucket.value.lower()]))
        or getattr(decision, f"{request.bucket.value.lower()}_action") != request.action.value
        or getattr(decision, "tactical_action" if request.bucket.value == "CORE" else "core_action")
        != "NONE"
        or Decimal(
            str(
                decision.position_after_proposed_json[
                    "tactical" if request.bucket.value == "CORE" else "core"
                ]
            )
        )
        != Decimal(
            str(
                decision.position_before_json[
                    "tactical" if request.bucket.value == "CORE" else "core"
                ]
            )
        )
        or Decimal(str(decision.position_after_proposed_json["total"]))
        - Decimal(str(decision.position_before_json["total"]))
        != output.delta_weight
    ):
        raise ValueError("SIZING_RECONSTRUCTION_MISMATCH")
    return request


def agent_opinion(record: AgentOpinionRecord, run: AgentRunRecord) -> AgentOpinion:
    # PR04 persists role/time provenance in AgentRun, but does not persist opinion.as_of.
    # Preserve that absence; the caller checks evidence against the actual run start.
    observations: object = record.observations_json
    if not isinstance(observations, list) or not all(
        isinstance(item, dict) for item in observations
    ):
        raise ValueError("OPINION_OBSERVATIONS_INVALID")
    return TypeAdapter(AgentOpinion).validate_python(
        {
            "role": run.agent_role,
            "instrument_id": record.instrument_id,
            "stance": record.stance,
            "confidence": {"value": record.confidence},
            "time_horizon": record.time_horizon,
            "observations": [
                {
                    "statement": fact["claim"],
                    "evidence_ids": fact["evidence_ids"],
                    "materiality": fact["materiality"],
                }
                for fact in observations
            ],
            "thesis_impacts": record.thesis_impacts_json,
            "assumptions": record.assumptions_json,
            "risks": record.risks_json,
            "invalidation_conditions": record.invalidation_conditions_json,
            "unknowns": record.unknowns_json,
            "schema_version": record.metadata_json["agent_opinion_schema_version"],
        }
    )
