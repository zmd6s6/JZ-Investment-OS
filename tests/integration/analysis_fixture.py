"""Explicit synthetic model output used only by analysis integration/E2E fixtures."""


def model_output(wrapper):
    role, value = wrapper["role"], wrapper["input"]
    frozen = value
    ids = [item["evidence_id"] for item in frozen["evidence"] if item["freshness"] == "FRESH"]
    reason = [{"text": "明确合成模型事实", "evidence_ids": ids}]
    if role == "PORTFOLIO":
        return {
            "schema_version": "portfolio-intent-1.0",
            "risk_intent": "NORMAL",
            "reasons": reason,
            "unknowns": [],
        }
    if role == "CIO":
        return {
            "schema_version": "cio-proposal-1.0",
            "proposed_action": "BUY",
            "reasons": reason,
            "unknowns": [],
        }
    return {
        "schema_version": "1.0",
        "agent_role": role,
        "instrument_id": frozen["instrument_id"],
        "as_of": frozen["as_of"],
        "stance": "POSITIVE",
        "confidence": "0.5",
        "time_horizon": "MONTHS",
        "observations": [{"claim": "合成事实", "evidence_ids": ids, "materiality": "MEDIUM"}],
        "thesis_impacts": [],
        "assumptions": [],
        "risks": [],
        "invalidation_conditions": [],
        "unknowns": [],
        "requested_followups": [],
    }
