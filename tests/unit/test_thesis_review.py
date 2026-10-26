"""A read projection of real observations must not become an automatic Thesis change."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_analysis_thesis import frozen

from investment_os.application.analysis_research import ResearchRecordView
from investment_os.application.errors import ApplicationError
from investment_os.application.thesis_review import (
    TeamThesisProvenance,
    TeamThesisReviewService,
    TeamThesisSource,
)


def fixture():
    thesis = frozen()
    evidence_id = thesis.evidence[0].evidence_id
    run_id, opinion_id = uuid4(), uuid4()
    run = SimpleNamespace(
        id=run_id,
        instrument_id=thesis.instrument_id,
        as_of=thesis.as_of,
        status="SUCCEEDED",
        payload={
            "input_snapshot": {
                "input_hash": "a" * 64,
                "thesis": thesis.snapshot(),
                "evidence": [{"evidence_id": str(evidence_id)}],
            }
        },
    )
    agent = {
        "role": "FUNDAMENTAL",
        "stage": "ROUND_1",
        "status": "SUCCEEDED",
        "error_code": None,
        "opinion_id": str(opinion_id),
        "unknowns": ["合成未决问题"],
        "observations": [{"claim": "合成观察", "evidence_ids": [str(evidence_id)]}],
    }
    records = ResearchRecordView(
        run_id=run_id,
        status="RECORDED",
        input_hash="a" * 64,
        agents=(agent,),
        risk={"gate": "VETO"},
    )
    return run, records, agent


class Read:
    def __init__(self, value):
        self.value = value

    async def get(self, _id):
        return self.value

    async def read(self, _id):
        return self.value


async def test_review_keeps_frozen_baseline_real_claims_unknowns_and_historical_veto():
    run, records, _ = fixture()
    view = await TeamThesisReviewService(Read(run), Read(records)).read(run.id)
    assert view.instrument_id == run.instrument_id
    assert str(view.base_version_id) == run.payload["input_snapshot"]["thesis"]["version"]["id"]
    assert view.suggestions[0].claim == "合成观察"
    assert view.suggestions[0].evidence_ids[0].hex
    assert view.unknowns == ("FUNDAMENTAL: 合成未决问题",) and view.risk_gate == "VETO"


@pytest.mark.parametrize("failed", [False, True])
async def test_second_round_replaces_first_and_failed_latest_never_reuses_old_claim(failed):
    run, records, agent = fixture()
    second = {
        **agent,
        "opinion_id": str(uuid4()),
        "stage": "ROUND_2",
        "status": "INSUFFICIENT_DATA" if failed else "SUCCEEDED",
        "observations": [
            {"claim": "第二轮合成观察", "evidence_ids": agent["observations"][0]["evidence_ids"]}
        ],
    }
    view = await TeamThesisReviewService(
        Read(run), Read(records.model_copy(update={"agents": (agent, second)}))
    ).read(run.id)
    assert [s.claim for s in view.suggestions] == ([] if failed else ["第二轮合成观察"])
    if failed:
        assert "FUNDAMENTAL: INSUFFICIENT_DATA" in view.unknowns


@pytest.mark.parametrize("bad", ["failed", "old", "hash", "instrument", "scope", "missing"])
async def test_missing_unfinished_or_mismatched_research_has_no_draft_fallback(bad):
    run, records, agent = fixture()
    if bad == "failed":
        run.status = "FAILED"
    if bad == "old":
        records = records.model_copy(update={"status": "NOT_RECORDED"})
    if bad == "hash":
        records = records.model_copy(update={"input_hash": "b" * 64})
    if bad == "instrument":
        run.instrument_id = uuid4()
    if bad == "scope":
        agent["observations"][0]["evidence_ids"] = [str(uuid4())]
    if bad == "missing":
        run.payload = {}
    with pytest.raises(ApplicationError) as failure:
        await TeamThesisReviewService(Read(run), Read(records)).read(run.id)
    assert failure.value.code.value == "THESIS_REVIEW_UNAVAILABLE"


def test_review_source_requires_nonempty_unique_bounded_selection():
    for ids in ((), ("one", "one"), tuple(str(i) for i in range(21))):
        with pytest.raises(ValidationError):
            TeamThesisSource(analysis_run_id=uuid4(), suggestion_ids=ids)


def test_impact_source_requires_unique_combined_bounded_selection():
    source = TeamThesisSource(analysis_run_id=uuid4(), impact_ids=("op:impact:0",))
    assert source.suggestion_ids == ()
    boundary = TeamThesisSource(
        analysis_run_id=uuid4(),
        suggestion_ids=("observation",),
        impact_ids=tuple(str(i) for i in range(19)),
    )
    assert len(boundary.suggestion_ids) + len(boundary.impact_ids) == 20
    legacy = TeamThesisProvenance.model_validate(
        {
            "analysis_run_id": uuid4(),
            "input_hash": "a" * 64,
            "suggestion_ids": ["op:0"],
            "opinion_ids": [uuid4()],
        }
    )
    assert legacy.impact_ids == ()
    for fields in (
        {"impact_ids": ("same", "same")},
        {"suggestion_ids": ("observation",), "impact_ids": tuple(str(i) for i in range(20))},
        {"impact_ids": ("",)},
    ):
        with pytest.raises(ValidationError):
            TeamThesisSource(analysis_run_id=uuid4(), **fields)


async def test_review_limit_is_explicit_not_fake_consensus():
    run, records, agent = fixture()
    agent["observations"] = [agent["observations"][0]] * 101
    records = records.model_copy(update={"agents": (agent,)})
    view = await TeamThesisReviewService(Read(run), Read(records)).read(run.id)
    assert len(view.suggestions) == 100
    assert "ADDITIONAL_OBSERVATIONS_NOT_SHOWN:1" in view.limitations


async def test_saved_impacts_keep_provenance_without_mutating_thesis():
    run, records, agent = fixture()
    original = str(run.payload)
    agent["thesis_impacts"] = [
        {
            "pillar_key": "demand",
            "impact": "WEAKEN",
            "reason": "合成削弱理由",
            "evidence_ids": agent["observations"][0]["evidence_ids"],
        }
    ]
    records = records.model_copy(update={"agents": (agent,)})
    view = await TeamThesisReviewService(Read(run), Read(records)).read(run.id)
    assert len(view.impacts) == 1
    assert view.impacts[0].impact == "WEAKEN"
    assert view.impacts[0].id == f"{agent['opinion_id']}:impact:0"
    again = await TeamThesisReviewService(Read(run), Read(records)).read(run.id)
    assert again.impacts == view.impacts
    assert view.impacts[0].baseline_status == "MATCHED"
    assert view.impacts[0].baseline_claim == "合成需求主张"
    assert str(view.impacts[0].opinion_id) == agent["opinion_id"]
    assert str(run.payload) == original


async def test_impact_reference_outside_run_is_rejected():
    run, records, agent = fixture()
    agent["thesis_impacts"] = [
        {
            "pillar_key": "P1",
            "impact": "BREAK",
            "reason": "合成判断",
            "evidence_ids": [str(uuid4())],
        }
    ]
    records = records.model_copy(update={"agents": (agent,)})
    with pytest.raises(ApplicationError):
        await TeamThesisReviewService(Read(run), Read(records)).read(run.id)


async def test_failed_second_round_does_not_reuse_first_round_impacts():
    run, records, agent = fixture()
    agent["thesis_impacts"] = [
        {
            "pillar_key": "P1",
            "impact": "STRENGTHEN",
            "reason": "合成判断",
            "evidence_ids": agent["observations"][0]["evidence_ids"],
        }
    ]
    second = {**agent, "stage": "ROUND_2", "status": "INSUFFICIENT_DATA", "thesis_impacts": []}
    view = await TeamThesisReviewService(
        Read(run), Read(records.model_copy(update={"agents": (agent, second)}))
    ).read(run.id)
    assert view.impacts == ()


async def test_impact_limit_preserves_explicit_omission_and_unmatched_key():
    run, records, agent = fixture()
    agent["thesis_impacts"] = [
        {
            "pillar_key": "unknown",
            "impact": "BREAK",
            "reason": "合成判断",
            "evidence_ids": agent["observations"][0]["evidence_ids"],
        }
    ] * 101
    records = records.model_copy(update={"agents": (agent,)})
    view = await TeamThesisReviewService(Read(run), Read(records)).read(run.id)
    assert len(view.impacts) == 100
    assert all(
        item.baseline_status == "UNMATCHED" and item.baseline_claim is None for item in view.impacts
    )
    assert "ADDITIONAL_IMPACTS_NOT_SHOWN:1" in view.limitations


async def test_valid_long_saved_reason_is_not_rejected_by_new_read_projection():
    run, records, agent = fixture()
    reason = "合成理由" * 1000
    agent["thesis_impacts"] = [
        {
            "pillar_key": "demand",
            "impact": "WEAKEN",
            "reason": reason,
            "evidence_ids": agent["observations"][0]["evidence_ids"],
        }
    ]
    records = records.model_copy(update={"agents": (agent,)})
    view = await TeamThesisReviewService(Read(run), Read(records)).read(run.id)
    assert view.impacts[0].reason == reason
