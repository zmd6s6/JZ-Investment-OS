"""Actual funnel origin, append-only intent and production analysis/worker composition."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import test_opportunity_funnel as funnel_fixture
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session
from test_analysis_pipeline import stack

from investment_os.application.opportunities import OpportunityError
from investment_os.application.opportunity_research import (
    CandidateResearchStart,
    OpportunityResearchService,
)
from investment_os.infrastructure.opportunity_research import SqlCandidateResearchStore
from investment_os.infrastructure.persistence.analysis_models import AnalysisRunRecord
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    EventLogRecord,
    OutboxEventRecord,
)

pytestmark = pytest.mark.integration


async def prepare_candidate(database_engine, monkeypatch):
    monkeypatch.setattr(funnel_fixture, "NOW", datetime.now(UTC) - timedelta(seconds=1))
    sessions, funnels, service, facts, query = await funnel_fixture.setup(database_engine)
    for fact in facts:
        await service.save_facts(fact)
    funnel = await service.run(query)
    assert len(funnel.candidate_ids) == 1
    return sessions, funnels, funnel


async def test_bounded_candidate_real_analysis_worker_and_concurrent_replay(
    database_engine, monkeypatch
):
    sessions, funnels, funnel = await prepare_candidate(database_engine, monkeypatch)
    _, analyses, _, _, _, start, runner, analysis, calls, client = await stack(database_engine)
    command = CandidateResearchStart(
        funnel_run_id=funnel.run_id,
        analysis=analysis.model_copy(
            update={
                "instrument_id": funnel.candidate_ids[0],
                "evidence_ids": funnel.rows[0].evidence_ids,
                "market_source_name": funnel.query.quote_source_name,
            }
        ),
    )
    intents = SqlCandidateResearchStore(sessions)
    service = OpportunityResearchService(funnels, intents, start, analyses)
    try:
        results = await asyncio.gather(*[service.start(command) for _ in range(4)])
        assert len({result.analysis_run.run_id for result in results}) == 1
        assert calls == []  # Saving origin/queue does not itself invoke a model.
        await runner.dispatch_due()
        history = await service.list_for(funnel.run_id)
        assert len(history) == 1 and history[0].command == command
        assert history[0].analysis_run.status.value == "DEGRADED"
        assert history[0].analysis_run.shadow_decision.action.value == "AVOID"
        assert history[0].analysis_run.shadow_decision.execution_allowed is False
        assert history[0].analysis_run.shadow_decision.target_quantity is None
        assert len(calls) == 9
        assert await funnels.get_run(funnel.run_id) == funnel
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(AnalysisRunRecord)) == 1
            for model in (EventLogRecord, AuditLogRecord, OutboxEventRecord):
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.created_by == "opportunity_research")
                    )
                    == 1
                )
        changed = command.model_copy(
            update={"analysis": command.analysis.model_copy(update={"portfolio_id": uuid4()})}
        )
        with pytest.raises(OpportunityError, match="REQUEST_CONTENT_CONFLICT"):
            await service.start(changed)
    finally:
        await client.aclose()


async def test_intent_outbox_failure_rolls_back_before_analysis_queue(database_engine, monkeypatch):
    sessions, funnels, funnel = await prepare_candidate(database_engine, monkeypatch)
    _, analyses, _, _, _, start, _, analysis, calls, client = await stack(database_engine)
    command = CandidateResearchStart(
        funnel_run_id=funnel.run_id,
        analysis=analysis.model_copy(
            update={
                "instrument_id": funnel.candidate_ids[0],
                "evidence_ids": funnel.rows[0].evidence_ids,
                "market_source_name": funnel.query.quote_source_name,
            }
        ),
    )
    service = OpportunityResearchService(
        funnels, SqlCandidateResearchStore(sessions), start, analyses
    )

    def reject_outbox(session, _context, _instances):
        if any(
            isinstance(row, OutboxEventRecord) and row.created_by == "opportunity_research"
            for row in session.new
        ):
            raise RuntimeError("synthetic outbox failure")

    event.listen(Session, "before_flush", reject_outbox)
    try:
        with pytest.raises(RuntimeError, match="synthetic outbox failure"):
            await service.start(command)
    finally:
        event.remove(Session, "before_flush", reject_outbox)
        await client.aclose()
    assert await service.list_for(funnel.run_id) == () and calls == []
    assert await analyses.find_request(command.analysis.request_id) is None


async def test_persisted_unqueued_intent_reads_without_automatic_restart(
    database_engine, monkeypatch
):
    sessions, funnels, funnel = await prepare_candidate(database_engine, monkeypatch)
    _, analyses, _, _, _, start, _, analysis, calls, client = await stack(database_engine)
    command = CandidateResearchStart(
        funnel_run_id=funnel.run_id,
        analysis=analysis.model_copy(
            update={
                "instrument_id": funnel.candidate_ids[0],
                "evidence_ids": funnel.rows[0].evidence_ids,
                "market_source_name": funnel.query.quote_source_name,
            }
        ),
    )
    intents = SqlCandidateResearchStore(sessions)
    await intents.record(command)  # Deterministic crash point between two transactions.
    service = OpportunityResearchService(funnels, intents, start, analyses)
    try:
        history = await service.list_for(funnel.run_id)
        assert history[0].analysis_run is None and history[0].status == "AWAITING_EXPLICIT_RETRY"
        assert calls == [] and await analyses.find_request(command.analysis.request_id) is None
        created = await service.start(command)
        assert created.analysis_run is not None
        assert len(await service.list_for(funnel.run_id)) == 1 and calls == []
    finally:
        await client.aclose()


async def test_production_app_candidate_routes_keep_write_auth_and_explicit_consent(
    database_engine, monkeypatch
):
    import httpx

    from investment_os.api.app import create_app

    sessions, funnels, funnel = await prepare_candidate(database_engine, monkeypatch)
    _, analyses, _, _, _, start, _, analysis, calls, model_client = await stack(database_engine)
    bridge = OpportunityResearchService(
        funnels, SqlCandidateResearchStore(sessions), start, analyses
    )
    command = CandidateResearchStart(
        funnel_run_id=funnel.run_id,
        analysis=analysis.model_copy(
            update={
                "instrument_id": funnel.candidate_ids[0],
                "evidence_ids": funnel.rows[0].evidence_ids,
                "market_source_name": funnel.query.quote_source_name,
            }
        ),
    )
    app = create_app(
        opportunity_research_service=bridge, write_api_token="synthetic-candidate-only"
    )
    data = command.model_dump(mode="json")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (
                await client.post("/api/v1/opportunities/research", json=data)
            ).status_code == 401
            headers = {"Authorization": "Bearer synthetic-candidate-only"}
            denied = data | {"analysis": data["analysis"] | {"allow_model_calls": False}}
            assert (
                await client.post("/api/v1/opportunities/research", headers=headers, json=denied)
            ).status_code == 422
            assert await bridge.list_for(funnel.run_id) == ()
            first = await client.post("/api/v1/opportunities/research", headers=headers, json=data)
            assert first.status_code == 202
            second = await client.post("/api/v1/opportunities/research", headers=headers, json=data)
            assert second.json()["analysis_run"]["run_id"] == first.json()["analysis_run"]["run_id"]
            history = await client.get(f"/api/v1/opportunities/runs/{funnel.run_id}/research")
            assert len(history.json()) == 1 and calls == []
    finally:
        await model_client.aclose()
