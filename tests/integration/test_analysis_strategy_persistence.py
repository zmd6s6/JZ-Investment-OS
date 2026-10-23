"""Test artifact identity is durable, unapproved and checked before paid work."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from test_analysis_jobs import jobs_setup

from investment_os.api.app import create_app
from investment_os.application.analysis_governance import AnalysisGovernancePlan
from investment_os.application.analysis_jobs import AnalysisWorkItem
from investment_os.application.analysis_orchestrator import AnalysisRunResult
from investment_os.application.errors import ApplicationError
from investment_os.infrastructure.analysis_strategy import EVENT, OWNER, SqlAnalysisStrategies
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    EventLogRecord,
    OutboxEventRecord,
    StrategyVersionRecord,
)


async def artifact_counts(sessions):
    async with sessions() as session:
        return [
            await session.scalar(statement)
            for statement in (
                select(func.count()).select_from(StrategyVersionRecord),
                select(func.count())
                .select_from(AuditLogRecord)
                .where(AuditLogRecord.operation == EVENT),
                select(func.count())
                .select_from(EventLogRecord)
                .where(EventLogRecord.event_type == EVENT),
                select(func.count())
                .select_from(OutboxEventRecord)
                .where(OutboxEventRecord.topic == "analysis.test_strategy"),
            )
        ]


async def test_concurrent_preparations_reuse_one_unapproved_artifact_and_atomic_receipt(
    database_engine,
):
    sessions, _, runs, product, _, jobs, inp = await jobs_setup(database_engine)
    prepared = await asyncio.gather(*(product.prepare(inp) for _ in range(4)))
    plan = prepared[0].request.governance
    strategy = plan.strategy
    assert all(p.request.governance.strategy == strategy for p in prepared)
    assert strategy.version == 1 and strategy.status == "DRAFT" and strategy.mode == "TEST_DEFAULT"
    assert not plan.allows_new_exposure
    assert strategy.formula == plan.formula and strategy.prompts == plan.prompts
    assert len(strategy.prompts) == 8 and strategy.code_ref.startswith("sha256:")
    assert await artifact_counts(sessions) == [1, 1, 1, 1]
    parsed = AnalysisWorkItem.model_validate_json(
        AnalysisWorkItem(request=prepared[0].request).model_dump_json()
    )
    assert parsed.request.governance == plan
    app = create_app(
        analysis_product_service=product, analysis_run_service=runs, analysis_job_service=jobs
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/v1/policy/review")).status_code == 200
        assert (await client.get("/api/v1/analysis-runs")).status_code == 200
    assert await artifact_counts(sessions) == [1, 1, 1, 1]  # GETs never register or activate.
    async with sessions() as session:
        row = await session.get(StrategyVersionRecord, strategy.id)
        assert row.approved_by is None and row.created_by == OWNER


async def test_changed_artifact_gets_new_version_without_rewriting_prior_rules(database_engine):
    sessions, _, _, product, _, _, inp = await jobs_setup(database_engine)
    first = (await product.prepare(inp)).request.governance
    catalog = SqlAnalysisStrategies(sessions)
    changed = first.model_copy(
        update={
            "strategy": None,
            "strategy_status": "NOT_CONFIGURED",
            "formula": first.formula.model_copy(update={"version": "synthetic-next"}),
        }
    )
    second = await catalog.freeze(changed)
    assert second.version == 2 and second.id != first.strategy.id
    assert second.content_hash != first.strategy.content_hash
    assert second.status == "DRAFT"
    await catalog.validate(first)
    assert await artifact_counts(sessions) == [2, 2, 2, 2]


async def test_registration_receipt_failure_rolls_back_artifact_and_audit(
    database_engine, monkeypatch
):
    sessions, _, _, product, _, _, inp = await jobs_setup(database_engine)

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic receipt failure")

    monkeypatch.setattr("investment_os.infrastructure.analysis_strategy.append_event", fail)
    with pytest.raises(RuntimeError, match="synthetic receipt failure"):
        await product.prepare(inp)
    assert await artifact_counts(sessions) == [0, 0, 0, 0]


@pytest.mark.parametrize("operation", ["update", "delete"])
async def test_registered_strategy_is_append_only(database_engine, operation):
    sessions, _, _, product, _, _, inp = await jobs_setup(database_engine)
    strategy = (await product.prepare(inp)).request.governance.strategy
    statement = (
        update(StrategyVersionRecord).values(status="ACTIVE")
        if operation == "update"
        else delete(StrategyVersionRecord)
    ).where(StrategyVersionRecord.id == strategy.id)
    with pytest.raises(DBAPIError):
        async with sessions() as session, session.begin():
            await session.execute(statement)
    assert await artifact_counts(sessions) == [1, 1, 1, 1]


@pytest.mark.parametrize(
    "bad", ["approval", "status", "creator", "prompts", "code", "content", "identity"]
)
async def test_malformed_or_approved_record_is_never_accepted_as_test_strategy(
    database_engine, bad
):
    sessions, _, _, product, _, _, inp = await jobs_setup(database_engine)
    plan = (await product.prepare(inp)).request.governance
    async with sessions() as session, session.begin():
        original = await session.get(StrategyVersionRecord, plan.strategy.id)
        values = {
            name: getattr(original, name)
            for name in (
                "status",
                "rules_json",
                "prompt_bundle_hash",
                "code_ref",
                "approved_by",
                "content_hash",
                "created_by",
            )
        }
        if bad == "approval":
            values["approved_by"] = "synthetic-owner"
        if bad == "status":
            values["status"] = "ACTIVE"
        if bad == "creator":
            values["created_by"] = "other-registry"
        if bad == "prompts":
            values["prompt_bundle_hash"] = "0" * 64
        if bad == "code":
            values["code_ref"] = "sha256:" + "0" * 64
        if bad == "content":
            values["rules_json"] = {**values["rules_json"], "mode": "ACTIVE"}
        row = StrategyVersionRecord(id=uuid4(), version=2, correlation_id=uuid4(), **values)
        session.add(row)
        await session.flush()
        other = plan.strategy.model_copy(
            update={"id": row.id, "version": 99 if bad == "identity" else 2}
        )
    changed = plan.model_copy(update={"strategy": other})
    with pytest.raises(ApplicationError) as failure:
        await SqlAnalysisStrategies(sessions).validate(changed)
    assert failure.value.code.value == "ANALYSIS_STRATEGY_INVALID"


async def test_queued_code_change_fails_before_models_and_explicit_retry_refreezes(
    database_engine, monkeypatch
):
    sessions, _, runs, product, _, jobs, inp = await jobs_setup(database_engine)
    original = await jobs.submit(uuid4(), inp)
    frozen = original.payload["input_snapshot"]["governance"]
    calls = []

    async def execute(request, **kwargs):
        calls.append(request)
        return AnalysisRunResult("FAILED", None, "SYNTHETIC", "合成结束")

    monkeypatch.setattr("investment_os.application.analysis_product.execute_analysis", execute)
    monkeypatch.setattr(
        "investment_os.infrastructure.analysis_strategy.runtime_code_ref",
        lambda: "sha256:" + "1" * 64,
    )
    assert await jobs.run_once()
    failed = await runs.get(original.id)
    assert failed.status == "FAILED" and failed.failure_code == "ANALYSIS_STRATEGY_CHANGED"
    assert calls == []  # execute_analysis contains both quote and model calls.
    assert failed.payload["input_snapshot"]["governance"] == frozen
    with pytest.raises(ApplicationError):
        await jobs.retry(original.id, uuid4())  # Hot-edited source needs a fresh runtime.
    product._strategies = SqlAnalysisStrategies(sessions)  # Simulate assembly after restart.
    retried = await jobs.retry(original.id, uuid4())
    next_strategy = retried.payload["input_snapshot"]["governance"]["strategy"]
    assert next_strategy["id"] != frozen["strategy"]["id"] and next_strategy["version"] == 2
    assert await jobs.run_once() and len(calls) == 1
    assert str(calls[0].governance.strategy.id) == next_strategy["id"]
    assert not calls[0].governance.allows_new_exposure
    assert await artifact_counts(sessions) == [2, 2, 2, 2]


async def test_missing_strategy_snapshot_or_catalog_does_not_call_model(
    database_engine, monkeypatch
):
    _, _, _, product, _, _, inp = await jobs_setup(database_engine)
    prepared = await product.prepare(inp)
    calls = []

    async def execute(*args, **kwargs):
        calls.append(args)

    monkeypatch.setattr("investment_os.application.analysis_product.execute_analysis", execute)
    old = AnalysisGovernancePlan.model_validate(
        {
            **prepared.request.governance.model_dump(),
            "strategy": None,
            "strategy_status": "NOT_CONFIGURED",
        }
    )
    assert (
        await product.execute_prepared(replace(prepared.request, governance=old))
    ).failure_code == "ANALYSIS_STRATEGY_SNAPSHOT_MISSING"
    product._strategies = None
    assert (
        await product.execute_prepared(prepared.request)
    ).failure_code == "ANALYSIS_STRATEGY_CHANGED"
    assert calls == []
