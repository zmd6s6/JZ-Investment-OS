"""模型前真实上下文提交、独立保留与租约 / 只追加边界。"""

import asyncio
import json
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from test_analysis_research import Gateway, configured

from investment_os.api.app import create_app
from investment_os.application.agent_runtime import AgentRuntime
from investment_os.application.analysis_jobs import AnalysisWorkItem
from investment_os.application.analysis_orchestrator import (
    AnalysisRunResult,
    _load_analysis_valuation,
    default_registry,
)
from investment_os.application.analysis_progress import AnalysisCancelled
from investment_os.application.committee_runtime import CommitteeRuntime
from investment_os.application.errors import ApplicationError
from investment_os.application.market_data import InMemoryMarketDataAdapter
from investment_os.infrastructure.analysis_execution_context import (
    EVENT,
    SqlAnalysisExecutionContexts,
)
from investment_os.infrastructure.analysis_research import SqlAnalysisResearchReader
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    EventLogRecord,
    FeatureSnapshotRecord,
    OutboxEventRecord,
)


class ProbeGateway(Gateway):
    def __init__(self, store, *, fail=False):
        super().__init__()
        self.store, self.fail = store, fail
        self.receipts = []

    async def complete(self, request):
        view = await self.store.read(request.budget_task_id)
        assert view.status == "RECORDED"
        assert view.receipt.runtime_input_hash == request.input_snapshot_hash
        assert json.loads(request.input_payload_json)["deterministic_portfolio_context"][
            "valuation"
        ] == view.valuation.model_dump(mode="json")
        self.receipts.append(view.receipt)
        if self.fail:
            raise RuntimeError("合成模型故障")
        return await super().complete(request)


async def context_counts(sessions):
    async with sessions() as session:
        return [
            await session.scalar(select(func.count()).select_from(table).where(condition))
            for table, condition in (
                (
                    FeatureSnapshotRecord,
                    FeatureSnapshotRecord.feature_set_version == "analysis-portfolio-context-v1",
                ),
                (EventLogRecord, EventLogRecord.event_type == EVENT),
                (AuditLogRecord, AuditLogRecord.operation == EVENT),
                (OutboxEventRecord, OutboxEventRecord.topic == "analysis.inputs"),
            )
        ]


@pytest.mark.parametrize("fail", [False, True])
async def test_context_commits_before_first_model_and_survives_failure(database_engine, fail):
    sessions, runs, product, _port, jobs, inp, _ = await configured(database_engine)
    store = SqlAnalysisExecutionContexts(sessions)
    gateway = ProbeGateway(store, fail=fail)
    product._committee = CommitteeRuntime(
        agent_runtime=AgentRuntime(registry=default_registry(), gateway=gateway)
    )
    run = await jobs.submit(uuid4(), inp)
    assert (await store.read(run.id)).status == "NOT_RECORDED"
    assert await jobs.run_once()
    finished = await runs.get(run.id)
    assert finished.status == ("FAILED" if fail else "SUCCEEDED")
    view = await store.read(run.id)
    assert view.status == "RECORDED" and await context_counts(sessions) == [1, 1, 1, 1]
    assert all(receipt == view.receipt for receipt in gateway.receipts)
    assert view.receipt.request_input_hash == run.payload["input_snapshot"]["input_hash"]
    assert view.receipt.runtime_input_hash != view.receipt.request_input_hash
    if not fail:
        assert gateway.calls == 8
        assert finished.payload["context_hash"] == view.receipt.runtime_input_hash
        research = await SqlAnalysisResearchReader(sessions).read(run.id)
        assert research.input_hash == view.receipt.request_input_hash
        assert research.runtime_input_hash == view.receipt.runtime_input_hash
        assert research.feature_snapshot_id == view.receipt.feature_snapshot_id
    else:
        assert (await SqlAnalysisResearchReader(sessions).read(run.id)).status == "NOT_RECORDED"
    assert (await runs.get(run.id)).payload["input_snapshot"] == run.payload["input_snapshot"]


async def test_context_commit_failure_rolls_back_and_never_calls_model(
    database_engine, monkeypatch
):
    sessions, runs, _product, _port, jobs, inp, gateway = await configured(database_engine)

    def fail(*args, **kwargs):
        raise RuntimeError("合成审计提交故障")

    monkeypatch.setattr(
        "investment_os.infrastructure.analysis_execution_context.append_event", fail
    )
    run = await jobs.submit(uuid4(), inp)
    assert await jobs.run_once()
    result = await runs.get(run.id)
    assert result.status == "FAILED" and result.failure_code == "ANALYSIS_CONTEXT_RECORDING_FAILED"
    assert gateway.calls == 0
    assert await context_counts(sessions) == [0, 0, 0, 0]


async def test_terminal_report_cannot_replace_the_context_used_by_models(database_engine):
    sessions, runs, product, port, jobs, inp, gateway = await configured(database_engine)
    run = await jobs.submit(uuid4(), inp)

    async def execute(req, progress, record):
        result = await product.execute_prepared(req, progress=progress, market_record=record)
        return replace(
            result,
            payload=replace(result.payload, valuation={**result.payload.valuation, "nav": "999"}),
        )

    assert await port.work_once(execute)
    finished = await runs.get(run.id)
    assert finished.status == "FAILED" and finished.failure_code == "ANALYSIS_RECORDING_FAILED"
    assert gateway.calls == 8
    assert (await SqlAnalysisExecutionContexts(sessions).read(run.id)).valuation.nav != 999
    assert (await SqlAnalysisResearchReader(sessions).read(run.id)).status == "NOT_RECORDED"


async def test_same_inputs_in_distinct_runs_reuse_the_real_feature_not_duplicate_it(
    database_engine,
):
    sessions, _runs, _product, port, jobs, inp, _gateway = await configured(database_engine)
    first = await jobs.submit(uuid4(), inp)
    second = await jobs.submit(uuid4(), replace(inp, as_of=first.as_of))
    store = SqlAnalysisExecutionContexts(sessions)

    async def execute(req, progress, record):
        value = await _load_analysis_valuation(req, InMemoryMarketDataAdapter())
        await store.save(req.budget_task_id, value, worker_token=req.execution_lease)
        return AnalysisRunResult("FAILED", None, "SYNTHETIC_STOP", "合成停止")

    assert await port.work_once(execute) and await port.work_once(execute)
    one, two = await store.read(first.id), await store.read(second.id)
    assert one.receipt.feature_snapshot_id == two.receipt.feature_snapshot_id
    assert one.receipt.run_id != two.receipt.run_id
    assert await context_counts(sessions) == [1, 2, 2, 2]


@pytest.mark.parametrize("stop", ["cancel", "stale_lease", "mismatch"])
async def test_context_rejects_cancel_stale_worker_and_wrong_frozen_portfolio(
    database_engine, stop
):
    sessions, _runs, _product, port, jobs, inp, gateway = await configured(database_engine)
    run = await jobs.submit(uuid4(), inp)
    store = SqlAnalysisExecutionContexts(sessions)

    async def execute(req, progress, record):
        value = await _load_analysis_valuation(req, InMemoryMarketDataAdapter())
        if stop == "cancel":
            await jobs.cancel(run.id)
        if stop == "mismatch":
            value = value.model_copy(update={"portfolio_id": uuid4()})
        with pytest.raises(ApplicationError if stop == "mismatch" else AnalysisCancelled):
            await store.save(
                run.id,
                value,
                worker_token=uuid4() if stop == "stale_lease" else req.execution_lease,
            )
        return AnalysisRunResult("FAILED", None, "SYNTHETIC_STOP", "合成停止")

    assert await port.work_once(execute)
    assert gateway.calls == 0 and await context_counts(sessions) == [0, 0, 0, 0]


async def test_context_same_run_concurrent_replay_reuses_and_snapshot_is_immutable(database_engine):
    sessions, _runs, _product, port, jobs, inp, _ = await configured(database_engine)
    run = await jobs.submit(uuid4(), inp)
    store = SqlAnalysisExecutionContexts(sessions)
    receipts = []

    async def execute(req, progress, record):
        value = await _load_analysis_valuation(req, InMemoryMarketDataAdapter())
        receipts.extend(
            await asyncio.gather(
                *(store.save(run.id, value, worker_token=req.execution_lease) for _ in range(3))
            )
        )
        with pytest.raises(ApplicationError):
            await store.save(
                run.id,
                value.model_copy(update={"input_hash": "f" * 64}),
                worker_token=req.execution_lease,
            )
        return AnalysisRunResult("FAILED", None, "SYNTHETIC_STOP", "合成停止")

    assert await port.work_once(execute)
    assert len(receipts) == 3 and receipts[0] == receipts[1] == receipts[2]
    assert await context_counts(sessions) == [1, 1, 1, 1]
    async with sessions() as session, session.begin():
        with pytest.raises(DBAPIError):
            await session.execute(
                text("UPDATE feature_snapshot SET values_json='{}'::jsonb WHERE id=:id"),
                {"id": receipts[0].feature_snapshot_id},
            )
    with pytest.raises(AnalysisCancelled):
        await store.save(run.id, (await store.read(run.id)).valuation)


async def test_context_api_read_only_old_run_and_local_session_auth(
    database_engine, tmp_path, monkeypatch
):
    _sessions, runs, product, _port, jobs, inp, gateway = await configured(database_engine)
    run = await jobs.submit(uuid4(), inp)
    from investment_os.infrastructure.local_access import LocalAccessStore
    from investment_os.infrastructure.settings import get_settings

    settings = get_settings().model_copy(
        update={"api_auth_mode": "local_session", "local_access_origin": "http://127.0.0.1"}
    )
    monkeypatch.setattr("investment_os.api.app.get_settings", lambda: settings)
    store = LocalAccessStore(tmp_path / "context-access.sqlite3")
    app = create_app(
        analysis_product_service=product,
        analysis_run_service=runs,
        write_api_token="synthetic-context-auth",
        local_access_store=store,
        local_access_origin="http://127.0.0.1",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.get(f"/api/v1/analysis-runs/{run.id}/execution-context")
        assert response.status_code == 401
        response = await client.get(
            f"/api/v1/analysis-runs/{run.id}/execution-context",
            headers={"Authorization": "Bearer synthetic-context-auth"},
        )
        assert response.status_code == 200 and response.json()["status"] == "NOT_RECORDED"
        missing = await client.get(
            f"/api/v1/analysis-runs/{uuid4()}/execution-context",
            headers={"Authorization": "Bearer synthetic-context-auth"},
        )
        assert missing.status_code == 404
    assert gateway.calls == 0


async def test_internal_work_item_cannot_persist_a_worker_lease(database_engine):
    _sessions, _runs, product, _port, _jobs, inp, _gateway = await configured(database_engine)
    request = (await product.prepare(inp)).request
    with pytest.raises(ValueError, match="runtime-only"):
        AnalysisWorkItem(request=replace(request, execution_lease=uuid4()))


async def test_missing_context_store_never_falls_back_to_unrecorded_models(database_engine):
    sessions, runs, product, _port, jobs, inp, gateway = await configured(database_engine)
    product._execution_contexts = None
    run = await jobs.submit(uuid4(), inp)
    assert await jobs.run_once()
    assert (await runs.get(run.id)).failure_code == "ANALYSIS_CONTEXT_RECORDING_FAILED"
    assert gateway.calls == 0 and await context_counts(sessions) == [0, 0, 0, 0]


@pytest.mark.parametrize("broken", ["missing", "content"])
async def test_context_reader_rejects_missing_or_changed_artifact_without_mutating_history(
    database_engine, monkeypatch, broken
):
    sessions, _runs, _product, _port, jobs, inp, gateway = await configured(database_engine)
    run = await jobs.submit(uuid4(), inp)
    assert await jobs.run_once()
    store = SqlAnalysisExecutionContexts(sessions)
    original = await store.read(run.id)
    real_get = AsyncSession.get

    async def faulty_get(session, entity, *args, **kwargs):
        record = await real_get(session, entity, *args, **kwargs)
        if entity is FeatureSnapshotRecord:
            if broken == "missing":
                return None
            from types import SimpleNamespace

            return SimpleNamespace(
                values_json={**record.values_json, "nav": "999"},
                created_by=record.created_by,
                instrument_id=record.instrument_id,
                as_of=record.as_of,
                feature_set_version=record.feature_set_version,
                input_hash=record.input_hash,
            )
        return record

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "get", faulty_get)
        with pytest.raises(ApplicationError):
            await store.read(run.id)
    assert await store.read(run.id) == original
    assert gateway.calls == 8
