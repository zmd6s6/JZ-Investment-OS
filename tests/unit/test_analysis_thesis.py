"""Historical Thesis inputs cannot invent validity, bypass evidence or drift in a queue."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from investment_os.application.analysis_jobs import AnalysisWorkItem
from investment_os.application.analysis_product import ProductAnalysisService
from investment_os.application.analysis_thesis import (
    AnalysisThesisInput,
    AnalysisThesisVersion,
    ThesisEvidenceInput,
)
from investment_os.application.thesis import thesis_content_hash
from investment_os.domain.enums import ThesisState
from investment_os.domain.thesis import (
    EvidenceBackedClaim,
    InvalidationCondition,
    PillarStatus,
    ThesisChangeReason,
    ThesisContent,
    ThesisPillar,
)

NOW = datetime.now(UTC)


def content(evidence_id, *, state=ThesisState.VALID, summary="合成长期投资逻辑"):
    return ThesisContent(
        state,
        summary,
        (
            ThesisPillar(
                "demand", EvidenceBackedClaim("合成需求主张", (evidence_id,)), PillarStatus.VALID
            ),
        ),
        (),
        (),
        (InvalidationCondition("合成需求失效", "demand", "below 1", "single observation"),),
        ("核对下一份合成公告",),
        ThesisChangeReason.NEW_EVIDENCE,
    )


def frozen(*, state=ThesisState.VALID, freshness="FRESH", expired=False):
    eid = uuid4()
    payload = content(eid, state=state)
    return AnalysisThesisInput(
        instrument_id=uuid4(),
        as_of=NOW,
        version=AnalysisThesisVersion(
            id=uuid4(),
            thesis_id=uuid4(),
            version=1,
            parent_version_id=None,
            created_at=NOW - timedelta(minutes=1),
            content_hash=thesis_content_hash(payload),
            content=payload,
        ),
        evidence=(
            ThesisEvidenceInput(
                evidence_id=eid,
                content_hash="c" * 64,
                available_at=NOW - timedelta(hours=2),
                ingested_at=NOW - timedelta(hours=1),
                expires_at=NOW if expired else NOW + timedelta(days=1),
                freshness=freshness,
            ),
        ),
    )


def test_missing_thesis_is_unknown_and_roundtrips():
    value = AnalysisThesisInput(instrument_id=uuid4(), as_of=NOW)
    assert value.state is ThesisState.UNKNOWN
    assert AnalysisThesisInput.model_validate_json(value.model_dump_json()) == value
    assert value.snapshot()["effective_state"] == "UNKNOWN"


@pytest.mark.parametrize(
    "state,freshness,expired,expected",
    [
        (ThesisState.VALID, "FRESH", False, ThesisState.VALID),
        (ThesisState.VALID, "STALE", False, ThesisState.UNKNOWN),
        (ThesisState.VALID, "EXPIRED", True, ThesisState.UNKNOWN),
        (ThesisState.BROKEN, "EXPIRED", True, ThesisState.BROKEN),
    ],
)
def test_frozen_thesis_keeps_history_but_stale_facts_cannot_authorize_exposure(
    state, freshness, expired, expected
):
    value = frozen(state=state, freshness=freshness, expired=expired)
    assert AnalysisThesisInput.model_validate_json(value.model_dump_json()) == value
    assert value.state is expected
    assert value.version.content.state is state


@pytest.mark.parametrize(
    "bad", ["hash", "links", "future", "future_ingestion", "false_fresh", "naive"]
)
def test_thesis_snapshot_rejects_invalid_provenance(bad):
    value = frozen()
    payload = value.model_dump(mode="json")
    if bad == "hash":
        payload["version"]["content_hash"] = "d" * 64
    if bad == "links":
        payload["evidence"] = []
    if bad == "future":
        payload["version"]["created_at"] = (NOW + timedelta(seconds=1)).isoformat()
    if bad == "future_ingestion":
        payload["evidence"][0]["ingested_at"] = (NOW + timedelta(seconds=1)).isoformat()
    if bad == "false_fresh":
        payload["evidence"][0]["expires_at"] = NOW.isoformat()
    if bad == "naive":
        payload["as_of"] = NOW.replace(tzinfo=None).isoformat()
    with pytest.raises(ValidationError):
        AnalysisThesisInput.model_validate_json(json.dumps(payload))


async def test_work_item_retains_actual_thesis_not_a_default():
    from test_analysis_governance import frozen_policy, request_for

    thesis = frozen()
    request = replace(
        request_for(frozen_policy()),
        instrument_id=thesis.instrument_id,
        as_of=NOW,
        thesis=thesis,
        thesis_state=thesis.state,
        thesis_version_id=thesis.version.id,
    )
    work = AnalysisWorkItem(request=request)
    restored = AnalysisWorkItem.model_validate_json(work.model_dump_json())
    assert restored.request.thesis == thesis


@pytest.mark.parametrize("bad", ["missing", "instrument", "state", "version", "time", "expired"])
async def test_bad_or_expired_queued_thesis_fails_before_models(bad):
    from test_analysis_governance import frozen_policy, request_for

    thesis = frozen()
    request = replace(
        request_for(frozen_policy()),
        instrument_id=thesis.instrument_id,
        as_of=NOW,
        thesis=thesis,
        thesis_state=thesis.state,
        thesis_version_id=thesis.version.id,
    )
    if bad == "missing":
        request = replace(request, thesis=None)
    if bad == "instrument":
        request = replace(request, instrument_id=uuid4())
    if bad == "state":
        request = replace(request, thesis_state=ThesisState.BROKEN)
    if bad == "version":
        request = replace(request, thesis_version_id=uuid4())
    if bad == "time":
        request = replace(request, as_of=NOW + timedelta(seconds=1))
    if bad == "expired":
        # The frozen request was valid before expiry; execute after it without rewriting history.
        class Clock:
            @staticmethod
            def now(tz):
                return NOW + timedelta(days=2)

        clock = patch("investment_os.application.analysis_product.datetime", Clock)
    else:
        from contextlib import nullcontext

        clock = nullcontext()
    service = ProductAnalysisService(
        inputs=None, portfolios=None, analysis_runs=None, committee=None, market_data=None
    )
    with (
        patch(
            "investment_os.application.analysis_product.execute_analysis", new_callable=AsyncMock
        ) as model,
        clock,
    ):
        result = await service.execute_prepared(request)
    assert result.status == "FAILED"
    assert result.failure_code.startswith("ANALYSIS_THESIS_")
    model.assert_not_awaited()


@pytest.mark.parametrize("broken", [False, True])
async def test_team_and_cio_use_fixed_thesis_without_promoting_historical_evidence(broken):
    from test_analysis_orchestrator import _portfolio, _response

    from investment_os.application.agent_runtime import AgentRuntime
    from investment_os.application.analysis_orchestrator import (
        AnalysisEvidenceSource,
        AnalysisRequest,
        default_registry,
        execute_analysis,
    )
    from investment_os.application.committee_runtime import CommitteeRuntime
    from investment_os.application.market_data import InMemoryMarketDataAdapter

    value = (
        frozen(state=ThesisState.BROKEN)
        if broken
        else AnalysisThesisInput(instrument_id=uuid4(), as_of=NOW)
    )
    selected = uuid4()
    calls = []

    class Gateway:
        async def complete(self, request):
            data = json.loads(request.input_payload_json)
            calls.append(data)
            response = _response(request.role, "NEUTRAL", str(value.instrument_id), str(selected))
            opinion = json.loads(response.raw_output)
            opinion["as_of"] = NOW.isoformat()
            return replace(response, raw_output=json.dumps(opinion))

    portfolio = _portfolio(value.instrument_id)
    portfolio = replace(
        portfolio, positions=(replace(portfolio.positions[0], tactical_quantity=Decimal("2")),)
    )
    request = AnalysisRequest(
        instrument_id=value.instrument_id,
        portfolio_id=portfolio.portfolio_id,
        portfolio=portfolio,
        as_of=NOW,
        policy_version_label="TEST_DEFAULT",
        evidence=(AnalysisEvidenceSource(selected, "b" * 64, NOW - timedelta(minutes=1)),),
        thesis=value,
        thesis_state=value.state,
        thesis_version_id=value.version.id if value.version else None,
    )
    result = await execute_analysis(
        request,
        committee=CommitteeRuntime(
            agent_runtime=AgentRuntime(registry=default_registry(), gateway=Gateway())
        ),
        market_data=InMemoryMarketDataAdapter(),
    )
    assert result.status == "SUCCEEDED" and len(calls) == 8
    assert all(item["thesis"] == value.snapshot() for item in calls)
    assert all(item["evidence_ids"] == [str(selected)] for item in calls)
    decision = result.payload.decision
    assert decision["thesis_state"] == value.state.value
    if broken:
        assert decision["thesis_version_id"] == str(value.version.id)
        assert decision["action"] == "REDUCE"
        assert decision["core_action"] == decision["tactical_action"] == "REDUCE"
        assert "THESIS_BROKEN_REVIEW_REQUIRED" in result.payload.failures
    else:
        assert decision["thesis_version_id"] is None
        assert next(g for g in decision["gates"] if g["gate"] == "THESIS")["outcome"] == "UNKNOWN"
