"""Strict content-command wire and canonical idempotency boundaries, no database needed."""

from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from investment_os.application.thesis_workspace import ThesisCommand


def payload():
    a, b = str(uuid4()), str(uuid4())
    return {
        "request_id": str(uuid4()),
        "instrument_id": str(uuid4()),
        "expected_version_id": None,
        "expected_content_hash": None,
        "actor_name": "合成研究员",
        "draft": {
            "state": "UNKNOWN",
            "long_term_summary": "合成摘要",
            "pillars": [
                {
                    "key": "P1",
                    "status": "AT_RISK",
                    "claim": {"description": "合成事实", "evidence_ids": [a, b]},
                }
            ],
            "catalysts": [],
            "risks": [],
            "invalidation_conditions": [],
            "monitoring_conditions": [],
            "change_reason": "HUMAN_CORRECTION",
        },
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("as_of", "2020-01-01T00:00:00Z"),
        ("full_review_completed", True),
        ("source_verified", True),
        ("schema_version", "2.0"),
        ("request_id", "bad"),
        ("actor_name", " "),
        ("expected_version_id", str(uuid4())),
        ("expected_content_hash", "a" * 64),
    ],
)
def test_human_command_rejects_untrusted_fields_invalid_identity_and_half_baseline(field, value):
    p = payload()
    p[field] = value
    with pytest.raises(ValidationError):
        ThesisCommand.model_validate(p)


@pytest.mark.parametrize(
    "mutation",
    [
        "blank_summary",
        "blank_claim",
        "missing_reference",
        "duplicate_reference",
        "duplicate_pillar",
        "unknown_field",
        "too_many_pillars",
        "unknown_state",
        "empty_monitoring",
        "blank_pillar_key",
    ],
)
def test_human_command_strict_domain_shape_rejects_malformed_structured_fields(mutation):
    p = payload()
    d = p["draft"]
    if mutation == "blank_summary":
        d["long_term_summary"] = " "
    elif mutation == "blank_claim":
        d["pillars"][0]["claim"]["description"] = " "
    elif mutation == "missing_reference":
        d["pillars"][0]["claim"]["evidence_ids"] = []
    elif mutation == "duplicate_reference":
        d["pillars"][0]["claim"]["evidence_ids"] *= 2
    elif mutation == "duplicate_pillar":
        d["pillars"] *= 2
    elif mutation == "unknown_field":
        d["approved"] = True
    elif mutation == "too_many_pillars":
        d["pillars"] *= 31
    elif mutation == "unknown_state":
        d["state"] = "APPROVED"
    elif mutation == "empty_monitoring":
        d["monitoring_conditions"] = [""]
    elif mutation == "blank_pillar_key":
        d["pillars"][0]["key"] = " "
    with pytest.raises(ValidationError):
        ThesisCommand.model_validate(p)


def test_canonical_hash_ignores_order_but_binds_instrument_actor_baseline_and_content():
    p = payload()
    a = ThesisCommand.model_validate(p)
    q = deepcopy(p)
    q["draft"]["pillars"][0]["claim"]["evidence_ids"].reverse()
    assert ThesisCommand.model_validate(q).canonical_hash() == a.canonical_hash()
    for field, value in (
        ("instrument_id", str(uuid4())),
        ("actor_name", "另一合成人"),
        ("request_id", str(uuid4())),
    ):
        assert (
            ThesisCommand.model_validate({**p, field: value}).canonical_hash() != a.canonical_hash()
        )
    q = deepcopy(p)
    q["draft"]["long_term_summary"] = "改动"
    assert ThesisCommand.model_validate(q).canonical_hash() != a.canonical_hash()


@pytest.mark.parametrize("bad_field", ["long_term_summary", "evidence_ids", "instrument_id"])
async def test_new_workspace_validation_names_chinese_fields_without_affecting_legacy_errors(
    bad_field,
):
    import httpx
    from fastapi import FastAPI

    from investment_os.api.thesis_workspace_routes import thesis_workspace_router

    app = FastAPI()
    app.include_router(thesis_workspace_router(None))

    @app.post("/legacy-validation")
    async def legacy(command: ThesisCommand):
        return None

    value = payload()
    expected = {
        "long_term_summary": "长期逻辑摘要",
        "evidence_ids": "引用证据",
        "instrument_id": "标的编号",
    }[bad_field]
    if bad_field == "long_term_summary":
        value["draft"][bad_field] = ""
    elif bad_field == "evidence_ids":
        value["draft"]["pillars"][0]["claim"][bad_field] = []
    else:
        value[bad_field] = "malformed"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/thesis-workspace/preview", json=value)
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "THESIS_INPUT_INVALID"
        assert expected in response.json()["detail"]["message"]
        assert "合成事实" not in response.json()["detail"]["message"]
        legacy_error = await client.post("/legacy-validation", json=value)
        assert legacy_error.status_code == 422 and isinstance(legacy_error.json()["detail"], list)
        path = await client.get("/api/v1/thesis-workspace/malformed")
        assert path.status_code == 422 and "标的编号" in path.json()["detail"]["message"]


@pytest.mark.parametrize("field", ["pillars", "catalysts", "risks"])
def test_workspace_reference_order_is_semantic_noop_for_every_claim_kind(field):
    from investment_os.application.thesis import thesis_content_hash, thesis_content_payload
    from investment_os.application.thesis_workspace import ThesisDraft, workspace_semantic_diff

    value = payload()
    ids = sorted(value["draft"]["pillars"][0]["claim"]["evidence_ids"])
    claim = {"description": "合成双引用事实", "evidence_ids": ids}
    if field == "pillars":
        value["draft"][field][0]["claim"] = claim
    else:
        value["draft"][field] = [claim]
    previous = ThesisCommand.model_validate(value).draft.domain()
    changed = deepcopy(value)
    target = changed["draft"][field][0]
    if field == "pillars":
        target = target["claim"]
    target["evidence_ids"].reverse()
    current = ThesisCommand.model_validate(changed).draft.domain()
    assert thesis_content_hash(previous) == thesis_content_hash(current)
    assert not workspace_semantic_diff(previous, current).is_material
    canonical = ThesisDraft.model_validate(thesis_content_payload(previous)).domain()
    assert not workspace_semantic_diff(canonical, current).is_material
    changed["draft"]["long_term_summary"] = "实质内容修订"
    assert workspace_semantic_diff(
        canonical, ThesisCommand.model_validate(changed).draft.domain()
    ).is_material
