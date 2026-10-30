"""Only a frozen bounded candidate can authorize one explicit analysis request."""

from uuid import uuid4

import pytest
from test_opportunities import NOW, inputs

from investment_os.application.analysis_runs import (
    ANALYSIS_ROLES,
    AnalysisRunView,
    AnalysisStart,
    analysis_command_payload,
)
from investment_os.application.opportunities import (
    FunnelRun,
    OpportunityError,
    StageResult,
    evaluate,
    query_rule_hash,
)
from investment_os.application.opportunity_research import (
    CandidateResearchStart,
    OpportunityResearchService,
)
from investment_os.application.portfolio_valuation import fingerprint


def candidate_inputs():
    entry, quote, facts, query = inputs()
    row = evaluate(entry, quote, facts, query)
    row = row.model_copy(
        update={
            "stages": (
                *row.stages,
                StageResult(stage="BOUND", status="PASSED", reason="WITHIN_LIMIT"),
            )
        }
    )
    funnel = FunnelRun(
        run_id=query.request_id,
        query=query,
        query_rule_hash=query_rule_hash(query),
        ingested_at=NOW,
        status="COMPLETE",
        rows=(row,),
        candidate_ids=(entry.instrument_id,),
    )
    command = CandidateResearchStart(
        funnel_run_id=funnel.run_id,
        analysis=AnalysisStart(
            request_id=uuid4(),
            portfolio_id=uuid4(),
            instrument_id=entry.instrument_id,
            model_profiles={role: uuid4() for role in ANALYSIS_ROLES},
            evidence_ids=row.evidence_ids,
            market_source_name=query.quote_source_name,
            allow_model_calls=True,
        ),
    )
    return funnel, command


def analysis_view(command):
    return AnalysisRunView(
        run_id=uuid4(),
        request_id=command.request_id,
        portfolio_id=command.portfolio_id,
        instrument_id=command.instrument_id,
        status="QUEUED",
        queued_at=NOW,
        started_at=None,
        finished_at=None,
        cancel_requested=False,
        retry_of=None,
        error_code=None,
        request_hash=fingerprint(analysis_command_payload(command)),
        input_hash=None,
        policy_version_id=None,
    )


class Ports:
    def __init__(self, funnel):
        self.funnel = funnel
        self.intents = {}
        self.runs = {}
        self.calls = 0
        self.fail_start = False

    async def get_run(self, identifier):
        return self.funnel if identifier == self.funnel.run_id else None

    async def record(self, command):
        identifier = command.analysis.request_id
        previous = self.intents.get(identifier)
        if previous and previous != command:
            raise OpportunityError("REQUEST_CONTENT_CONFLICT")
        self.intents[identifier] = command
        return command

    async def start(self, command):
        assert command.request_id in self.intents
        self.calls += 1
        if self.fail_start:
            raise ValueError("ANALYSIS_MODEL_PROFILE_UNAVAILABLE")
        if command.request_id not in self.runs:
            self.runs[command.request_id] = analysis_view(command)
        return self.runs[command.request_id]

    async def find_request(self, identifier):
        return self.runs.get(identifier)

    async def list_for(self, identifier):
        return tuple(c for c in self.intents.values() if c.funnel_run_id == identifier)


@pytest.mark.parametrize("change", ["target", "source", "evidence", "origin"])
async def test_non_candidate_or_unproven_input_never_records_intent_or_starts_analysis(change):
    funnel, command = candidate_inputs()
    ports = Ports(funnel)
    service = OpportunityResearchService(ports, ports, ports, ports)
    if change == "origin":
        command = command.model_copy(update={"funnel_run_id": uuid4()})
    else:
        command = command.model_copy(
            update={
                "analysis": command.analysis.model_copy(
                    update={
                        "target": {"instrument_id": uuid4()},
                        "source": {"market_source_name": "another"},
                        "evidence": {"evidence_ids": ()},
                    }[change]
                )
            }
        )
    with pytest.raises(OpportunityError):
        await service.start(command)
    assert ports.calls == 0 and ports.intents == {}


async def test_queue_failure_keeps_explicit_intent_and_requires_manual_same_request_retry():
    funnel, command = candidate_inputs()
    ports = Ports(funnel)
    ports.fail_start = True
    service = OpportunityResearchService(ports, ports, ports, ports)
    with pytest.raises(ValueError):
        await service.start(command)
    pending = await service.list_for(funnel.run_id)
    assert pending[0].status == "AWAITING_EXPLICIT_RETRY" and pending[0].analysis_run is None
    assert ports.calls == 1  # Reads never replay an unconfirmed paid request.
    ports.fail_start = False
    first = await service.start(command)
    second = await service.start(command)
    assert first.analysis_run == second.analysis_run
    assert len(ports.runs) == 1 and len(ports.intents) == 1
    assert first.status == "ANALYSIS_RECORDED" and first.auto_trade is False


async def test_same_request_changed_authorization_is_rejected_before_analysis():
    funnel, command = candidate_inputs()
    ports = Ports(funnel)
    service = OpportunityResearchService(ports, ports, ports, ports)
    await service.start(command)
    changed = command.model_copy(
        update={"analysis": command.analysis.model_copy(update={"portfolio_id": uuid4()})}
    )
    with pytest.raises(OpportunityError, match="REQUEST_CONTENT_CONFLICT"):
        await service.start(changed)
    assert ports.calls == 1


async def test_linked_analysis_mismatch_is_not_displayed_as_candidate_research():
    funnel, command = candidate_inputs()
    ports = Ports(funnel)
    service = OpportunityResearchService(ports, ports, ports, ports)
    await service.start(command)
    ports.runs[command.analysis.request_id] = ports.runs[command.analysis.request_id].model_copy(
        update={"instrument_id": uuid4()}
    )
    with pytest.raises(OpportunityError, match="CANDIDATE_ANALYSIS_MISMATCH"):
        await service.list_for(funnel.run_id)


async def test_foreign_existing_request_cannot_poison_candidate_origin_history():
    funnel, command = candidate_inputs()
    ports = Ports(funnel)
    ports.runs[command.analysis.request_id] = analysis_view(command.analysis).model_copy(
        update={"portfolio_id": uuid4()}
    )
    service = OpportunityResearchService(ports, ports, ports, ports)
    with pytest.raises(OpportunityError, match="CANDIDATE_ANALYSIS_MISMATCH"):
        await service.start(command)
    assert ports.intents == {} and ports.calls == 0


async def test_router_without_research_composition_reports_unavailable_not_success():
    import httpx
    from fastapi import FastAPI

    from investment_os.api.opportunity_routes import opportunity_router

    _, command = candidate_inputs()
    app = FastAPI()
    app.include_router(opportunity_router(None))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/opportunities/research", json=command.model_dump(mode="json")
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "CANDIDATE_RESEARCH_UNAVAILABLE"
        capabilities = (await client.get("/api/v1/opportunities/capabilities")).json()
        assert capabilities["deep_research"] == "NOT_PROVIDED"
