"""Durable attempt boundaries under cancellation, interruption and write failures."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from test_analysis_jobs import configure_markets, jobs_setup

from investment_os.api.app import create_app
from investment_os.application.analysis_market import MarketAttempt, MarketAttemptEvent
from investment_os.application.analysis_orchestrator import AnalysisRunResult
from investment_os.application.analysis_progress import AnalysisCancelled
from investment_os.infrastructure.analysis_jobs import SqlAlchemyAnalysisJobs
from investment_os.infrastructure.analysis_market import PlannedMarketDataFactory
from investment_os.infrastructure.analysis_market_audit import EVENT_TYPE, SqlAnalysisMarketAudit
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    EventLogRecord,
    OutboxEventRecord,
)


@pytest.mark.parametrize("mode", ["normal", "cancel", "interrupt"])
async def test_market_audit_survives_terminal_state_without_replay(database_engine, mode):
    sessions, _, runs, product, port, jobs, inp = await jobs_setup(database_engine)
    settings, profiles = await configure_markets(sessions)
    run = await jobs.submit(uuid4(), replace(inp, market_profile_ids=tuple(p.id for p in profiles)))
    calls, callbacks = [], []

    class Source:
        name = "SYNTHETIC"

        def __init__(self, profile):
            self.profile = profile

        async def get_quotes(self, batch, *, as_of):
            # A separate connection already sees STARTED before any adapter operation.
            saved = await SqlAnalysisMarketAudit(sessions).events(run.id)
            assert saved[-1].attempt.status == "STARTED"
            calls.append(self.profile.id)
            if mode == "interrupt":
                raise asyncio.CancelledError()
            if mode == "cancel":
                await jobs.cancel(run.id)
            return {}

    market = PlannedMarketDataFactory(
        settings, settings._secret_store, {"TUSHARE_MARKET": lambda p, *a: Source(p)}
    )

    async def execute(request, progress, record):
        callbacks.append(record)
        await market.for_plan(request.market_plan, lambda a: None, record).get_reference_quotes(
            (request.instrument_id,),
            as_of=request.as_of,
            instruments={request.instrument_id: ("SSE", "600519", "CNY")},
        )
        return AnalysisRunResult("FAILED", None, "SYNTHETIC", "合成终止")

    if mode == "interrupt":
        with pytest.raises(asyncio.CancelledError):
            await port.work_once(execute)
        assert await SqlAlchemyAnalysisJobs(database_engine, sessions).work_once(execute)
    else:
        assert await port.work_once(execute)
    assert len(callbacks) == 1
    assert len(calls) == (2 if mode == "normal" else 1)
    assert not await port.work_once(execute)
    terminal = await runs.get(run.id)
    assert terminal.status == ("CANCELLED" if mode == "cancel" else "FAILED")
    assert terminal.payload["input_snapshot"] == run.payload["input_snapshot"]
    ledger = await SqlAnalysisMarketAudit(sessions).events(run.id)
    assert [e.attempt.status for e in ledger] == (
        ["STARTED", "NO_DATA", "STARTED", "NO_DATA"]
        if mode == "normal"
        else ["STARTED", "NO_DATA"]
        if mode == "cancel"
        else ["STARTED"]
    )
    with pytest.raises(AnalysisCancelled):
        await callbacks[0](ledger[0])  # Old worker cannot write after termination/recovery.
    app = create_app(
        analysis_product_service=product, analysis_run_service=runs, analysis_job_service=jobs
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/api/v1/analysis-runs/{run.id}/market-attempts")
        assert response.status_code == 200
        assert response.json() == [e.model_dump(mode="json") for e in ledger]
        assert (
            await client.get(f"/api/v1/analysis-runs/{uuid4()}/market-attempts")
        ).status_code == 404
    async with sessions() as session:
        for model, condition in (
            (EventLogRecord, EventLogRecord.event_type == EVENT_TYPE),
            (AuditLogRecord, AuditLogRecord.operation == EVENT_TYPE),
            (OutboxEventRecord, OutboxEventRecord.topic == "analysis.market"),
        ):
            assert await session.scalar(
                select(func.count()).select_from(model).where(condition)
            ) == len(ledger)
        rows = await session.scalars(
            select(OutboxEventRecord).where(OutboxEventRecord.topic == "analysis.market")
        )
        assert all(
            "queries" not in str(row.payload_json)
            and "synthetic-market-only" not in str(row.payload_json)
            for row in rows
        )


async def test_market_event_validation_idempotency_and_atomic_rollback(
    database_engine, monkeypatch
):
    sessions, _, runs, product, _, _, inp = await jobs_setup(database_engine)
    _, profiles = await configure_markets(sessions)
    prepared = await product.prepare(replace(inp, market_profile_ids=(profiles[0].id,)))
    run_id = await runs.mark_running(
        instrument_id=inp.instrument_id,
        portfolio_id=inp.portfolio_id,
        source=inp.source,
        as_of=prepared.request.as_of,
        policy_version_label=prepared.request.policy_version_label,
        input_snapshot=prepared.snapshot,
    )
    audit = SqlAnalysisMarketAudit(sessions)
    attempt = MarketAttempt(
        profile_id=profiles[0].id,
        name=profiles[0].name,
        provider_type="TUSHARE_MARKET",
        rank=0,
        status="STARTED",
        queries=("SSE:600519",),
    )
    event = MarketAttemptEvent(attempt_id=uuid4(), occurred_at=datetime.now(UTC), attempt=attempt)
    with pytest.raises(ValueError, match="requires committed start"):
        await audit.append(
            run_id,
            event.model_copy(update={"attempt": attempt.model_copy(update={"status": "NO_DATA"})}),
        )
    with pytest.raises(ValueError, match="frozen plan"):
        await audit.append(
            run_id,
            event.model_copy(
                update={"attempt": attempt.model_copy(update={"profile_id": uuid4()})}
            ),
        )

    def broken(*args, **kwargs):
        raise RuntimeError("synthetic outbox failure")

    with monkeypatch.context() as patch:
        patch.setattr(
            "investment_os.infrastructure.analysis_market_audit.OutboxEventRecord", broken
        )
        with pytest.raises(RuntimeError):
            await audit.append(run_id, event)
    assert await audit.events(run_id) == ()
    await audit.append(run_id, event)
    await audit.append(run_id, event)
    assert await audit.events(run_id) == (event,)
    finished = event.model_copy(
        update={
            "occurred_at": datetime.now(UTC),
            "attempt": attempt.model_copy(update={"status": "NO_DATA"}),
        }
    )
    await audit.append(run_id, finished)
    with pytest.raises(ValueError, match="transition"):
        await audit.append(run_id, finished.model_copy(update={"occurred_at": datetime.now(UTC)}))
    assert await audit.events(run_id) == (event, finished)
