"""Actual PostgreSQL analysis claims, atomic history and cancellation/recovery."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from investment_os.application.analysis_runs import (
    ANALYSIS_ROLES,
    AnalysisFrozenInput,
    AnalysisQueuedInput,
    AnalysisStart,
    EvidenceReason,
    SelectedModel,
    ShadowDecision,
)
from investment_os.application.instrument_catalog import InstrumentCatalogService
from investment_os.application.portfolio_book import PortfolioBookService
from investment_os.application.portfolio_valuation import PortfolioValuationService, fingerprint
from investment_os.application.research import ResearchArtifactDTO
from investment_os.domain.analysis_run import AnalysisStatus
from investment_os.domain.enums import Action, RiskIntent
from investment_os.domain.instrument import InstrumentIdentity
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.analysis_runs import AnalysisCancelled, SqlAnalysisRuns
from investment_os.infrastructure.catalog_portfolio import (
    SessionCatalogPort,
    SessionPortfolioBookPort,
)
from investment_os.infrastructure.evidence_ingestion import SqlAlchemyEvidenceIngestor
from investment_os.infrastructure.persistence.analysis_models import (
    AnalysisRunRecord,
    AnalysisShadowDecisionRecord,
    AnalysisStepRecord,
)
from investment_os.infrastructure.persistence.models import EventLogRecord
from investment_os.infrastructure.portfolio_valuation import SqlValuationInputs

pytestmark = pytest.mark.integration


class NoMarket:
    async def get_snapshot(self, request):
        raise AssertionError("cash-only valuation has no quote request")


async def prepare(database_engine):
    sessions = async_sessionmaker(database_engine, expire_on_commit=False)
    catalog = SessionCatalogPort(sessions)
    instrument = await InstrumentCatalogService(catalog).register(
        InstrumentIdentity(
            market="SSE",
            symbol="629203",
            name="合成分析标的",
            asset_type="EQUITY",
            currency="CNY",
            sector="Synthetic",
        )
    )
    book = await PortfolioBookService(SessionPortfolioBookPort(sessions), catalog).create_portfolio(
        name="合成分析组合", base_currency="CNY", cash_balance="100"
    )
    valuation = await PortfolioValuationService(
        SqlValuationInputs(sessions), NoMarket()
    ).get_context(book.portfolio_id, source="MANUAL_MARKET", source_name="合成来源")
    profile = uuid4()
    command = AnalysisStart(
        request_id=uuid4(),
        portfolio_id=book.portfolio_id,
        instrument_id=instrument.instrument_id,
        model_profiles={role: profile for role in ANALYSIS_ROLES},
        market_source_name="合成来源",
        allow_model_calls=True,
    )
    snapshot = AnalysisQueuedInput(
        command=command,
        queued_at=datetime.now(UTC),
        valuation=valuation,
        models={
            role: SelectedModel(
                profile_id=profile,
                name="合成模型",
                model_name="synthetic",
                config_hash="a" * 64,
                timeout_seconds=10,
                max_tokens=500,
            )
            for role in ANALYSIS_ROLES
        },
        data_profiles=(),
        budget_hash="b" * 64,
    )
    return sessions, SqlAnalysisRuns(sessions), snapshot


async def frozen_input(sessions, run_id, queued):
    from investment_os.application.analysis_runs import AnalysisEvidenceInput

    now = datetime.now(UTC)
    receipt = await SqlAlchemyEvidenceIngestor(sessions, now=lambda: now).ingest(
        ResearchArtifactDTO(
            provider="SYNTHETIC",
            provider_ref="analysis-test",
            artifact_type="NEWS",
            instrument_id=queued.command.instrument_id,
            source_name="合成来源",
            source_locator="synthetic://analysis203",
            source_tier="PRIMARY",
            observed_at=UtcTimestamp(now - timedelta(hours=1)),
            effective_at=UtcTimestamp(now - timedelta(hours=1)),
            available_at=UtcTimestamp(now - timedelta(minutes=30)),
            expires_at=UtcTimestamp(now + timedelta(days=1)),
            payload={"body": "合成公开研究事实"},
            source_schema_version="synthetic-v1",
        )
    )
    from investment_os.infrastructure.persistence.models import EvidenceRecord

    async with sessions() as session:
        row = await session.get(EvidenceRecord, receipt.evidence_id)
    evidence = AnalysisEvidenceInput(
        evidence_id=row.id,
        instrument_id=row.instrument_id,
        content_hash=row.content_hash,
        source_name=row.source_name,
        source_locator=row.source_locator,
        source_tier=row.source_tier,
        observed_at=row.observed_at,
        effective_at=row.effective_at,
        available_at=row.available_at,
        ingested_at=row.ingested_at,
        expires_at=row.expires_at,
        quality_score="1",
        freshness="FRESH",
        payload_json='{"body":"synthetic research"}',
    )
    value = AnalysisFrozenInput(
        run_id=run_id,
        as_of=datetime.now(UTC),
        instrument_id=queued.command.instrument_id,
        queued=queued,
        evidence=(evidence,),
        thesis_version_id=None,
        thesis_state="UNKNOWN",
        thesis_json=None,
        input_hash="",
    )
    return value.model_copy(
        update={"input_hash": fingerprint(value.model_dump(mode="json", exclude={"input_hash"}))}
    )


async def test_analysis_request_claim_is_atomic_idempotent_and_conflicting_content_rejected(
    database_engine,
):
    sessions, store, snapshot = await prepare(database_engine)
    runs = await asyncio.gather(*(store.enqueue(snapshot) for _ in range(6)))
    assert len({run.run_id for run in runs}) == 1
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(AnalysisRunRecord)) == 1
    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventLogRecord)
                .where(EventLogRecord.event_type == "analysis.queued")
            )
            == 1
        )
    changed = snapshot.model_copy(
        update={"command": snapshot.command.model_copy(update={"market_source_name": "another"})}
    )
    with pytest.raises(ValueError, match="REQUEST_CONFLICT"):
        await store.enqueue(changed)
    claims = await asyncio.gather(*(store.claim_next() for _ in range(6)))
    assert sum(claim is not None for claim in claims) == 1
    assert (await store.get(runs[0].run_id)).status == AnalysisStatus.RUNNING


async def test_analysis_frozen_input_shadow_and_terminal_history_are_immutable(database_engine):
    sessions, store, queued = await prepare(database_engine)
    run = await store.enqueue(queued)
    run_id, lease, _ = await store.claim_next()
    frozen = await frozen_input(sessions, run_id, queued)
    await store.freeze(run_id, lease, frozen)
    result = ShadowDecision(
        action=Action.WATCH,
        risk_intent=RiskIntent.NONE,
        risk_gate="UNKNOWN",
        policy_version_id=None,
        thesis_version_id=None,
        reasons=(
            EvidenceReason(text="合成待观察", evidence_ids=(frozen.evidence[0].evidence_id,)),
        ),
        blockers=("MISSING_POLICY",),
        input_hash=frozen.input_hash,
    )
    await store.step(
        run_id, lease, stage="SIZING", status="BLOCKED", payload={"reason": "MISSING_INPUTS"}
    )
    await store.finish(run_id, lease, status=AnalysisStatus.DEGRADED, result=result)
    saved = await store.get(run.run_id)
    assert saved.shadow_decision == result and saved.frozen_input == frozen
    assert saved.steps[0].stage == "SIZING" and saved.finished_at is not None
    for query in [
        "UPDATE analysis_input SET input_hash = 'tampered'",
        "DELETE FROM analysis_shadow_decision",
        "UPDATE analysis_run SET status = 'QUEUED'",
    ]:
        with pytest.raises(DBAPIError):
            async with sessions() as session, session.begin():
                await session.execute(text(query))
    assert (await store.get(run.run_id)).shadow_decision == result
    with pytest.raises(ValueError):
        ShadowDecision(
            action=Action.BUY,
            risk_intent=RiskIntent.NORMAL,
            risk_gate="PASS",
            policy_version_id=None,
            thesis_version_id=None,
            reasons=result.reasons,
            blockers=(),
            input_hash=frozen.input_hash,
        )


async def test_cancel_is_idempotent_and_running_cancel_never_keeps_a_success_shadow(
    database_engine,
):
    sessions, store, queued = await prepare(database_engine)
    cancelled = await store.enqueue(queued)
    await store.cancel(cancelled.run_id)
    await store.cancel(cancelled.run_id)
    assert (await store.get(cancelled.run_id)).status == AnalysisStatus.CANCELLED
    assert await store.claim_next() is None
    queued = queued.model_copy(
        update={"command": queued.command.model_copy(update={"request_id": uuid4()})}
    )
    await store.enqueue(queued)
    run_id, lease, _ = await store.claim_next()
    await store.cancel(run_id)
    with pytest.raises(AnalysisCancelled):
        await store.check_running(run_id, lease)
    await store.finish(run_id, lease, status=AnalysisStatus.CANCELLED)
    assert (await store.get(run_id)).shadow_decision is None
    async with sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(AnalysisShadowDecisionRecord))
            == 0
        )


async def test_worker_interruption_is_terminal_and_never_silently_replays_paid_work(
    database_engine,
):
    _, store, queued = await prepare(database_engine)
    run = await store.enqueue(queued)
    await store.claim_next()
    assert await store.expire_interrupted(older_than=datetime.now(UTC) + timedelta(seconds=1)) == 1
    saved = await store.get(run.run_id)
    assert (
        saved.status == AnalysisStatus.FAILED
        and saved.error_code == "ANALYSIS_INTERRUPTED_RETRY_REQUIRED"
    )
    assert await store.claim_next() is None
    retried = queued.model_copy(
        update={
            "command": queued.command.model_copy(
                update={"request_id": uuid4(), "retry_of": run.run_id}
            )
        }
    )
    retry = await store.enqueue(retried)
    assert retry.run_id != run.run_id and retry.retry_of == run.run_id
    assert (await store.get(run.run_id)).status == AnalysisStatus.FAILED


async def test_step_event_outbox_and_audit_roll_back_together(database_engine, monkeypatch):
    sessions, store, queued = await prepare(database_engine)
    await store.enqueue(queued)
    run_id, lease, _ = await store.claim_next()
    import investment_os.infrastructure.analysis_runs as module

    original = module.emit

    async def fail(session, record, kind, payload):
        await original(session, record, kind, payload)
        raise RuntimeError("synthetic transaction failure")

    monkeypatch.setattr(module, "emit", fail)
    with pytest.raises(RuntimeError):
        await store.step(run_id, lease, stage="FEATURES", status="COMPLETED", payload={"count": 1})
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(AnalysisStepRecord)) == 0
    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventLogRecord)
                .where(EventLogRecord.event_type == "analysis.stage")
            )
            == 0
        )
