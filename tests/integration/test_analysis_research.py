"""Real analysis completion publishes normalized records or rolls back the whole batch."""

import json
from dataclasses import replace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from test_analysis_jobs import jobs_setup

from investment_os.api.app import create_app
from investment_os.application.agent_runtime import AgentRuntime
from investment_os.application.analysis_orchestrator import default_registry
from investment_os.application.committee_runtime import CommitteeRuntime
from investment_os.application.llm_gateway import LLMGatewayResponse
from investment_os.infrastructure.analysis_research import SqlAnalysisResearchReader
from investment_os.infrastructure.persistence.models import (
    AgentOpinionEvidenceRecord,
    AgentOpinionRecord,
    AgentRunRecord,
    AnalysisJobRecord,
    CommitteeMessageRecord,
    CommitteeSessionRecord,
    EventLogRecord,
    InvestmentDecisionRecord,
    OutboxEventRecord,
    RiskAssessmentEvidenceRecord,
    RiskAssessmentRecord,
)


class Gateway:
    def __init__(self, mode="PASS"):
        self.calls = 0
        self.mode = mode
        self.inputs = []

    async def complete(self, request):
        self.calls += 1
        value = json.loads(request.input_payload_json)
        self.inputs.append(value)
        data = {
            "schema_version": "1.0",
            "agent_role": request.role.value,
            "instrument_id": value["instrument"]["instrument_id"],
            "as_of": value["as_of"],
            "stance": "NEUTRAL",
            "confidence": "0.6",
            "time_horizon": "DAYS",
            "observations": [
                {
                    "claim": "合成可追溯事实",
                    "evidence_ids": value["evidence_ids"][:1],
                    "materiality": "LOW",
                }
            ],
            "thesis_impacts": [],
            "assumptions": [],
            "risks": [],
            "unknowns": [],
            "invalidation_conditions": [],
            "requested_followups": [],
        }
        if self.mode == "IMPACT" and request.role.value == "FUNDAMENTAL":
            data["thesis_impacts"] = [
                {
                    "pillar_key": "demand",
                    "impact": "WEAKEN",
                    "reason": "合成团队影响理由",
                    "evidence_ids": value["evidence_ids"][:1],
                }
            ]
        if request.role.value == "RISK" and self.mode == "VETO":
            data["risks"] = [
                {
                    "code": "SYNTHETIC_HARD",
                    "severity": "CRITICAL",
                    "evidence_ids": value["evidence_ids"][:1],
                }
            ]
        return LLMGatewayResponse(
            provider="SYNTHETIC",
            model_name="fixture-only",
            latency_ms=1,
            input_tokens=10,
            output_tokens=20,
            raw_output="{}"
            if request.role.value == "RISK" and self.mode == "UNKNOWN"
            else json.dumps(data),
        )


async def configured(engine, mode="PASS"):
    sessions, _, runs, product, port, jobs, inp = await jobs_setup(engine)
    gateway = Gateway(mode)
    product._committee = CommitteeRuntime(
        agent_runtime=AgentRuntime(registry=default_registry(), gateway=gateway)
    )
    return sessions, runs, product, port, jobs, inp, gateway


async def counts(sessions):
    async with sessions() as session:
        return [
            await session.scalar(select(func.count()).select_from(table))
            for table in (
                CommitteeSessionRecord,
                AgentRunRecord,
                AgentOpinionRecord,
                RiskAssessmentRecord,
                InvestmentDecisionRecord,
            )
        ]


async def test_saved_thesis_impacts_reach_review_without_writing_or_model_replay(database_engine):
    from investment_os.application.thesis_review import TeamThesisReviewService

    sessions, runs, _, _, jobs, inp, gateway = await configured(database_engine, "IMPACT")
    run = await jobs.submit(uuid4(), inp)
    assert await jobs.run_once()
    before = await runs.get(run.id)
    counts_before = await counts(sessions)
    reader = SqlAnalysisResearchReader(sessions)
    raw = await reader.read(run.id)
    agent = next(a for a in raw.agents if a["role"] == "FUNDAMENTAL")
    assert agent["thesis_impacts"][0]["reason"] == "合成团队影响理由"
    view = await TeamThesisReviewService(runs, reader).read(run.id)
    assert len(view.impacts) == 1
    assert view.impacts[0].baseline_status == "NO_BASELINE"
    assert view.impacts[0].opinion_id == UUID(agent["opinion_id"])
    assert await counts(sessions) == counts_before
    assert (await runs.get(run.id)).payload == before.payload and gateway.calls == 8


@pytest.mark.parametrize("mode", ["PASS", "VETO", "UNKNOWN"])
async def test_completed_analysis_records_actual_agents_risk_and_immutable_links(
    database_engine, mode
):
    sessions, runs, product, port, jobs, inp, gateway = await configured(database_engine, mode)
    run = await jobs.submit(uuid4(), inp)

    async def execute(req, progress, record):
        return await product.execute_prepared(req, progress=progress, market_record=record)

    assert await port.work_once(execute)
    completed = await runs.get(run.id)
    assert completed.status == "SUCCEEDED"
    assert completed.payload["valuation"]["calculation_version"] == "portfolio-valuation-v1"
    assert completed.payload["valuation"]["nav"] is not None  # cash-only snapshot is known
    assert completed.payload["valuation"]["target_reference_price"] is None
    assert completed.payload["sizing"]["status"] == "BLOCKED"
    assert "target_quantity" not in completed.payload["sizing"]
    assert "SIZING_CONTEXT_INCOMPLETE" in completed.payload["failures"]
    strategy = run.payload["input_snapshot"]["governance"]["strategy"]
    assert completed.payload["decision"]["strategy_version_id"] == strategy["id"]
    assert completed.payload["decision"]["strategy_content_hash"] == strategy["content_hash"]
    assert all(
        data["strategy"]["id"] == strategy["id"]
        and data["strategy"]["status"] == "DRAFT"
        and data["strategy"]["code_ref"] == strategy["code_ref"]
        for data in gateway.inputs
    )
    view = await SqlAnalysisResearchReader(sessions).read(run.id)
    assert (
        view.status == "RECORDED" and view.input_hash == run.payload["input_snapshot"]["input_hash"]
    )
    assert len(view.agents) == 8 and view.risk["gate"] == mode
    assert view.decision_status == "NOT_REGISTERED"
    assert await counts(sessions) == [1, 8, 8, 1, 0]
    assert all(a["started_at"] and a["ended_at"] and a["prompt_hash"] for a in view.agents)
    assert len({a["agent_run_id"] for a in view.agents}) == 8
    risk_agent = next(a for a in view.agents if a["role"] == "RISK")
    assert risk_agent["status"] == ("INSUFFICIENT_DATA" if mode == "UNKNOWN" else "SUCCEEDED")
    assert bool(view.risk["veto"]) == (mode == "VETO")
    assert bool(view.risk["evidence_ids"]) == (mode != "UNKNOWN")
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(CommitteeMessageRecord)) == 6
        assert await session.scalar(
            select(func.count()).select_from(AgentOpinionEvidenceRecord)
        ) == (7 if mode == "UNKNOWN" else 8)
        assert await session.scalar(
            select(func.count()).select_from(RiskAssessmentEvidenceRecord)
        ) == (0 if mode == "UNKNOWN" else 1)
        event = await session.scalar(
            select(EventLogRecord).where(EventLogRecord.event_type == "ANALYSIS_RESEARCH_RECORDED")
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OutboxEventRecord)
                .where(OutboxEventRecord.event_id == event.id)
            )
            == 1
        )
        job = await session.get(AnalysisJobRecord, run.id)
        token = job.worker_token
    before = gateway.calls
    # Re-reading a completed result does not quote, call models or alter its valuation.
    assert (await runs.get(run.id)).payload["valuation"] == completed.payload["valuation"]
    from investment_os.application.analysis_orchestrator import AnalysisRunResult

    await port._finish(run.id, token, AnalysisRunResult("FAILED", None, "LATE", "late"))
    assert (await runs.get(run.id)).status == "SUCCEEDED"
    assert (await SqlAnalysisResearchReader(sessions).read(run.id)) == view
    assert gateway.calls == before


@pytest.mark.parametrize("background", [True, False])
async def test_research_outbox_failure_cannot_publish_success_or_partial_records(
    database_engine, monkeypatch, background
):
    sessions, runs, product, port, jobs, inp, gateway = await configured(database_engine)

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic persistence failure")

    monkeypatch.setattr("investment_os.infrastructure.analysis_research.append_event", fail)
    if background:
        run = await jobs.submit(uuid4(), inp)

        async def execute(req, progress, record):
            return await product.execute_prepared(req, progress=progress, market_record=record)

        await port.work_once(execute)
        result = await runs.get(run.id)
    else:
        result = await product.start(inp)
    assert result.status == "FAILED" and result.failure_code == "ANALYSIS_RECORDING_FAILED"
    assert "opinions" not in result.payload and "research_records" not in result.payload
    assert await counts(sessions) == [0, 0, 0, 0, 0]
    assert gateway.calls == 8


async def test_cancel_after_models_finish_does_not_publish_research(database_engine):
    sessions, runs, product, port, jobs, inp, gateway = await configured(database_engine)
    run = await jobs.submit(uuid4(), inp)

    async def execute(req, progress, record):
        result = await product.execute_prepared(req, progress=progress, market_record=record)
        await port.cancel(run.id)
        return result

    await port.work_once(execute)
    assert (await runs.get(run.id)).status == "CANCELLED" and gateway.calls == 8
    assert await counts(sessions) == [0, 0, 0, 0, 0]
    assert (await SqlAnalysisResearchReader(sessions).read(run.id)).status == "NOT_RECORDED"


async def test_stale_worker_cannot_publish_research_before_current_worker(database_engine):
    sessions, runs, product, port, jobs, inp, _ = await configured(database_engine)
    run = await jobs.submit(uuid4(), inp)

    async def execute(req, progress, record):
        result = await product.execute_prepared(req, progress=progress, market_record=record)
        await port._finish(run.id, uuid4(), result)
        assert (await runs.get(run.id)).status == "RUNNING"
        assert await counts(sessions) == [0, 0, 0, 0, 0]
        return result

    await port.work_once(execute)
    assert (await runs.get(run.id)).status == "SUCCEEDED"
    assert await counts(sessions) == [1, 8, 8, 1, 0]


async def test_wrong_context_hash_fails_closed_without_model_replay(database_engine):
    sessions, runs, product, port, jobs, inp, gateway = await configured(database_engine)
    run = await jobs.submit(uuid4(), inp)

    async def execute(req, progress, record):
        result = await product.execute_prepared(req, progress=progress, market_record=record)
        return replace(
            result,
            research=replace(
                result.research,
                context=replace(result.research.context, input_snapshot_hash="f" * 64),
            ),
        )

    await port.work_once(execute)
    assert (await runs.get(run.id)).failure_code == "ANALYSIS_RECORDING_FAILED"
    assert await counts(sessions) == [0, 0, 0, 0, 0] and gateway.calls == 8


async def test_sync_analysis_and_read_only_api_use_real_tables_without_backfill(database_engine):
    sessions, runs, product, _, _, inp, gateway = await configured(database_engine)
    completed = await product.start(inp)
    assert completed.status == "SUCCEEDED" and await counts(sessions) == [1, 8, 8, 1, 0]
    old = await runs.record_success(
        instrument_id=inp.instrument_id,
        portfolio_id=inp.portfolio_id,
        source="RESEARCH",
        as_of=completed.as_of,
        policy_version_label="TEST_DEFAULT",
        payload={},
    )
    app = create_app(
        analysis_research_reader=SqlAnalysisResearchReader(sessions),
        write_api_token="synthetic-research-records",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        path = f"/api/v1/analysis-runs/{completed.id}/research-records"
        before = gateway.calls
        value = (await client.get(path)).json()
        assert value["status"] == "RECORDED" and len(value["agents"]) == 8
        assert "raw_output" not in json.dumps(value)
        assert (await client.get(f"/api/v1/analysis-runs/{old.id}/research-records")).json()[
            "status"
        ] == "NOT_RECORDED"
        assert (
            await client.get(f"/api/v1/analysis-runs/{uuid4()}/research-records")
        ).status_code == 404
        assert (await client.post(path, json={})).status_code == 401
        assert (
            await client.post(
                path, json={}, headers={"Authorization": "Bearer synthetic-research-records"}
            )
        ).status_code == 405
        assert gateway.calls == before and await counts(sessions) == [1, 8, 8, 1, 0]


async def test_sync_lost_commit_acknowledgement_keeps_original_success_and_records(
    database_engine, monkeypatch
):
    sessions, runs, product, _, _, inp, gateway = await configured(database_engine)
    original = runs._port.update_status

    async def lose_ack(*args, **kwargs):
        result = await original(*args, **kwargs)
        if kwargs.get("research") is not None:
            raise ConnectionError("synthetic commit acknowledgement loss")
        return result

    monkeypatch.setattr(runs._port, "update_status", lose_ack)
    result = await product.start(inp)
    assert result.status == "SUCCEEDED" and gateway.calls == 8
    view = await SqlAnalysisResearchReader(sessions).read(result.id)
    assert view.status == "RECORDED" and await counts(sessions) == [1, 8, 8, 1, 0]
    same = await runs.finish(result.id, status="FAILED", payload={"stage": "late"})
    assert same == result
