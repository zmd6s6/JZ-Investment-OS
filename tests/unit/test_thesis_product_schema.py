import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from investment_os.application.thesis_product import SaveThesisCommand
from investment_os.domain.enums import ThesisState
from investment_os.domain.errors import DomainError


def payload():
    return {
        "request_id": str(uuid4()),
        "expected_version_id": None,
        "content": {
            "state": "UNKNOWN",
            "long_term_summary": "合成逻辑",
            "pillars": [
                {
                    "key": "P1",
                    "status": "VALID",
                    "claim": {"description": "合成主张", "evidence_ids": [str(uuid4())]},
                }
            ],
            "catalysts": [],
            "risks": [],
            "invalidation_conditions": [],
            "monitoring_conditions": [],
            "change_reason": "HUMAN_CORRECTION",
        },
    }


def test_thesis_command_roundtrip_is_versioned_and_does_not_approve_anything():
    command = SaveThesisCommand.model_validate_json(json.dumps(payload()))
    assert command.schema_version == "1.0"
    assert command.content.to_domain().state is ThesisState.UNKNOWN
    assert SaveThesisCommand.model_validate_json(command.model_dump_json()) == command


@pytest.mark.parametrize(
    "bad",
    [
        "unknown",
        "nested",
        "empty",
        "oversized",
        "missing_base",
        "missing_evidence",
        "duplicates",
        "broken",
    ],
)
def test_thesis_command_rejects_invalid_content_or_unknown_authority(bad):
    value = payload()
    if bad == "unknown":
        value["approve"] = True
    if bad == "nested":
        value["content"]["pillars"][0]["claim"]["source_tier"] = "PRIMARY"
    if bad == "empty":
        value["content"]["long_term_summary"] = " "
    if bad == "oversized":
        value["content"]["long_term_summary"] = "x" * 3001
    if bad == "missing_base":
        del value["expected_version_id"]
    if bad == "missing_evidence":
        value["content"]["pillars"][0]["claim"]["evidence_ids"] = []
    if bad == "duplicates":
        value["content"]["pillars"][0]["claim"]["evidence_ids"] *= 2
    if bad == "broken":
        value["content"]["state"] = "BROKEN"
    with pytest.raises((ValidationError, DomainError)):
        SaveThesisCommand.model_validate_json(json.dumps(value)).content.to_domain()
