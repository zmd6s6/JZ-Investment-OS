"""Master-Spec §6.2 drift checks for the untrusted AgentOpinion wire boundary."""

from investment_os.application.agent_opinion import AgentOpinionPayload


def test_agent_opinion_wire_contract_matches_master_spec_section_6_2() -> None:
    schema = AgentOpinionPayload.model_json_schema()

    assert set(schema["required"]) == {
        "schema_version",
        "agent_role",
        "instrument_id",
        "as_of",
        "stance",
        "confidence",
        "time_horizon",
        "observations",
        "thesis_impacts",
        "assumptions",
        "risks",
        "invalidation_conditions",
        "unknowns",
        "requested_followups",
    }
    assert "role" not in schema["properties"]
    assert schema["properties"]["schema_version"]["const"] == "1.0"
    assert schema["properties"]["time_horizon"]["enum"] == [
        "DAYS",
        "WEEKS",
        "MONTHS",
        "QUARTERS",
        "YEARS",
    ]
