import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from test_research_previews import Secrets, preview, setup

from investment_os.api.app import create_app
from investment_os.application.analysis_jobs import AnalysisJobError, AnalysisJobService
from investment_os.application.analysis_market import AnalysisMarketConfiguration
from investment_os.application.analysis_models import AnalysisModelConfiguration
from investment_os.application.analysis_orchestrator import AnalysisRunResult
from investment_os.application.analysis_product import ProductAnalysisService, StartAnalysisInput
from investment_os.application.analysis_run import AnalysisRunService
from investment_os.application.llm_gateway import LLMGatewayResponse
from investment_os.application.portfolio_book import PortfolioBookService
from investment_os.application.provider_settings import ProviderSettingsService
from investment_os.infrastructure.analysis_inputs import SqlAlchemyAnalysisInputs
from investment_os.infrastructure.analysis_jobs import SqlAlchemyAnalysisJobs
from investment_os.infrastructure.analysis_market import PlannedMarketDataFactory
from investment_os.infrastructure.analysis_run_store import SessionAnalysisRunPort
from investment_os.infrastructure.analysis_worker import AnalysisWorker
from investment_os.infrastructure.catalog_portfolio import (
    SessionCatalogPort,
    SessionPortfolioBookPort,
)
from investment_os.infrastructure.persistence.models import (
    AnalysisJobRecord,
    AnalysisProgressRecord,
    AnalysisRunRecord,
    EventLogRecord,
    ModelProviderProfileRecord,
    OutboxEventRecord,
)
from investment_os.infrastructure.provider_settings import SqlAlchemyProviderSettingsStore
from investment_os.infrastructure.settings import Settings


async def jobs_setup(engine):
    factory, _, profile, target, research, _, _, client = await setup(engine)
    draft = await preview(research, profile, target)
    evidence_id = (
        await research.confirm(
            draft.preview_id, target.instrument_id, (draft.candidates[0].candidate_id,)
        )
    )[0].evidence_id
    catalog = SessionCatalogPort(factory)
    portfolios = PortfolioBookService(SessionPortfolioBookPort(factory), catalog)
    portfolio = await portfolios.create_portfolio(
        name="合成后台任务组合", base_currency="CNY", cash_balance="10000"
    )
    runs = AnalysisRunService(SessionAnalysisRunPort(factory))
    models = await configure_models(factory)
    secrets = Secrets()
    market_settings = ProviderSettingsService(SqlAlchemyProviderSettingsStore(factory), secrets)
    markets = PlannedMarketDataFactory(market_settings, secrets)
    product = ProductAnalysisService(
        inputs=SqlAlchemyAnalysisInputs(factory),
        portfolios=portfolios,
        analysis_runs=runs,
        committee=None,
        market_data=None,
        catalog=catalog,
        model_configuration=models,
        market_configuration=AnalysisMarketConfiguration(market_settings, markets.supported_types),
        market_factory=markets,
    )
    port = SqlAlchemyAnalysisJobs(engine, factory)
    service = AnalysisJobService(port, product)
    inp = StartAnalysisInput(
        target.instrument_id, portfolio.portfolio_id, "RESEARCH", evidence_ids=(evidence_id,)
    )
    await client.aclose()
    return factory, portfolios, runs, product, port, service, inp


async def configure_models(factory):
    settings = ProviderSettingsService(SqlAlchemyProviderSettingsStore(factory), Secrets())
    profile = await settings.save_model_profile(
        profile_id=None,
        name="合成分析模型",
        provider_type="OPENAI_COMPATIBLE",
        base_url="https://models.example.test/v1",
        model_name="synthetic-model",
        timeout_seconds=30,
        max_tokens=2048,
        enabled=True,
        credential="synthetic-test-only",
        pricing_version="synthetic-v1",
        pricing_currency="USD",
        input_token_price=Decimal("0.000001"),
        output_token_price=Decimal("0.000002"),
    )
    await settings.save_role_assignment(role="DEFAULT", model_provider_profile_id=profile.id)
    return AnalysisModelConfiguration(settings)


async def configure_markets(factory):
    settings = ProviderSettingsService(SqlAlchemyProviderSettingsStore(factory), Secrets())
    profiles = []
    for name in ("合成主行情", "合成备行情"):
        profiles.append(
            await settings.save_data_profile(
                profile_id=None,
                name=name,
                provider_type="TUSHARE_MARKET",
                base_url="https://api.tushare.pro",
                timeout_seconds=5,
                enabled=True,
                credential="synthetic-market-only",
                retention_days=30,
            )
        )
    return settings, profiles


async def test_market_api_freezes_order_rejects_stale_and_preserves_idempotent_snapshot(
    database_engine,
):
    factory, _, runs, product, _, jobs, inp = await jobs_setup(database_engine)
    settings, profiles = await configure_markets(factory)
    app = create_app(
        analysis_product_service=product,
        analysis_run_service=runs,
        analysis_job_service=jobs,
        write_api_token="synthetic-market-auth",
    )
    headers = {"Authorization": "Bearer synthetic-market-auth"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        options = (await client.get("/api/v1/analysis-market-options")).json()
        assert {p["profile_id"] for p in options["profiles"]} == {str(p.id) for p in profiles}
        assert "credential" not in json.dumps(options) and "https://" not in json.dumps(options)
        ids = [str(p.id) for p in reversed(profiles)]
        body = {
            "request_id": str(uuid4()),
            "instrument_id": str(inp.instrument_id),
            "portfolio_id": str(inp.portfolio_id),
            "market_profile_ids": ids,
            "market_configuration_hash": options["configuration_hash"],
        }
        response = await client.post("/api/v1/analysis-jobs", json=body, headers=headers)
        assert response.status_code == 202
        frozen = response.json()["payload"]["input_snapshot"]["market_plan"]
        assert [p["profile_id"] for p in frozen["profiles"]] == ids
        assert (
            await client.post(
                "/api/v1/analysis-jobs",
                json={**body, "market_profile_ids": ids[::-1]},
                headers=headers,
            )
        ).status_code == 409
        profile = profiles[0]
        await settings.save_data_profile(
            profile_id=profile.id,
            name=profile.name,
            provider_type=profile.provider_type,
            base_url=profile.base_url,
            timeout_seconds=6,
            enabled=True,
            credential=None,
            retention_days=30,
        )
        replay = await client.post("/api/v1/analysis-jobs", json=body, headers=headers)
        assert replay.json()["payload"]["input_snapshot"]["market_plan"] == frozen
        stale = await client.post(
            "/api/v1/analysis-jobs", json={**body, "request_id": str(uuid4())}, headers=headers
        )
        assert (
            stale.status_code == 422
            and stale.json()["detail"] == "ANALYSIS_MARKET_CONFIGURATION_CHANGED"
        )
        duplicate = await client.post(
            "/api/v1/analysis-jobs",
            json={
                **body,
                "request_id": str(uuid4()),
                "market_configuration_hash": None,
                "market_profile_ids": [ids[0], ids[0]],
            },
            headers=headers,
        )
        assert duplicate.status_code == 422
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(AnalysisJobRecord)) == 1


async def test_queued_market_change_stops_before_models_retry_keeps_order_and_refreezes(
    database_engine,
):
    factory, _, runs, product, port, jobs, inp = await jobs_setup(database_engine)
    settings, profiles = await configure_markets(factory)
    selected = tuple(p.id for p in reversed(profiles))
    run = await jobs.submit(uuid4(), replace(inp, market_profile_ids=selected))
    original = run.payload["input_snapshot"]
    profile = profiles[0]
    await settings.save_data_profile(
        profile_id=profile.id,
        name=profile.name,
        provider_type=profile.provider_type,
        base_url=profile.base_url,
        timeout_seconds=6,
        enabled=True,
        credential=None,
        retention_days=30,
    )
    assert product._committee is None  # Any model execution would fail rather than pass silently.
    assert await jobs.run_once()
    failed = await runs.get(run.id)
    assert (
        failed.status == "FAILED" and failed.failure_code == "ANALYSIS_MARKET_CONFIGURATION_CHANGED"
    )
    assert failed.payload["input_snapshot"] == original
    assert (await port.retry_input(run.id)).market_profile_ids == selected
    new_run = await jobs.retry(run.id, uuid4())
    new_plan = new_run.payload["input_snapshot"]["market_plan"]["profiles"]
    assert [UUID(p["profile_id"]) for p in new_plan] == list(selected)
    assert (
        new_plan[1]["configuration_hash"]
        != original["market_plan"]["profiles"][1]["configuration_hash"]
    )
    assert (await runs.get(run.id)).payload["input_snapshot"] == original


async def test_omitted_market_selection_never_auto_adds_enabled_profiles(database_engine):
    factory, _, _, product, _, _, inp = await jobs_setup(database_engine)
    await configure_markets(factory)
    for choice in (None, ()):
        prepared = await product.prepare(replace(inp, market_profile_ids=choice))
        assert prepared.snapshot["market_plan"]["profiles"] == []
        assert prepared.request.market_plan.profiles == ()


async def test_concurrent_submit_claim_and_restart_keep_frozen_inputs(database_engine):
    factory, portfolios, runs, _, port, service, inp = await jobs_setup(database_engine)
    request_id = uuid4()
    first, second = await asyncio.gather(
        service.submit(request_id, inp), service.submit(request_id, inp)
    )
    assert first.id == second.id and first.status == second.status == "QUEUED"
    with pytest.raises(AnalysisJobError, match="conflict"):
        await service.submit(request_id, StartAnalysisInput(uuid4(), inp.portfolio_id))
    await portfolios.set_cash_balance(inp.portfolio_id, "20000")
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def execute(request, progress):
        calls.append(request)
        assert request.portfolio.cash_balance == Decimal("10000")
        await progress("ROUND_ONE", "STARTED")
        started.set()
        await release.wait()
        await progress("ROUND_ONE", "COMPLETED")
        return AnalysisRunResult("FAILED", None, "SYNTHETIC_FAILURE", "合成失败")

    worker = asyncio.create_task(port.work_once(execute))
    await asyncio.wait_for(started.wait(), timeout=10)
    restarted = SqlAlchemyAnalysisJobs(database_engine, factory)
    assert await restarted.work_once(execute) is False
    assert (await runs.get(first.id)).status == "RUNNING"
    release.set()
    assert await worker is True
    assert len(calls) == 1
    result = await runs.get(first.id)
    assert (
        result.status == "FAILED"
        and result.payload["input_snapshot"] == first.payload["input_snapshot"]
    )
    assert [item.sequence for item in await restarted.events(first.id)] == [1, 2, 3, 4, 5]
    assert await restarted.work_once(execute) is False
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(AnalysisJobRecord)) == 1
        stages = await session.scalar(
            select(func.count())
            .select_from(EventLogRecord)
            .where(EventLogRecord.event_type == "ANALYSIS_STAGE")
        )
        outbox = await session.scalar(
            select(func.count())
            .select_from(OutboxEventRecord)
            .where(OutboxEventRecord.topic == "analysis.jobs")
        )
        assert stages == outbox == 5


@pytest.mark.parametrize("running", [False, True])
async def test_cancel_is_idempotent_and_stops_next_paid_stage(database_engine, running):
    factory, _, runs, _, port, service, inp = await jobs_setup(database_engine)
    run = await service.submit(uuid4(), inp)
    calls = []

    async def execute(request, progress):
        calls.append("first")
        await progress("ROUND_ONE", "STARTED")
        await service.cancel(run.id)
        await service.cancel(run.id)
        await progress("ROUND_ONE", "COMPLETED")
        calls.append("forbidden-next-stage")
        return AnalysisRunResult("SUCCEEDED", None)

    if not running:
        await service.cancel(run.id)
        await service.cancel(run.id)
        assert await port.work_once(execute) is False
    else:
        assert await port.work_once(execute) is True
    assert calls == (["first"] if running else [])
    result = await runs.get(run.id)
    assert result.status == "CANCELLED"
    assert result.payload["input_snapshot"] == run.payload["input_snapshot"]
    events = await port.events(run.id)
    assert sum(e.stage == "CANCEL_REQUESTED" for e in events) == (1 if running else 0)
    async with factory() as session:
        assert (await session.get(AnalysisJobRecord, run.id)).finished_at is not None


async def test_process_interruption_never_replays_paid_call_and_retry_is_new_run(database_engine):
    factory, portfolios, runs, _, port, service, inp = await jobs_setup(database_engine)
    run = await service.submit(uuid4(), inp)
    calls = []

    async def interrupted(request, progress):
        calls.append(request)
        await progress("ROUND_ONE", "STARTED")
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await port.work_once(interrupted)
    assert (await runs.get(run.id)).status == "RUNNING"
    restarted = SqlAlchemyAnalysisJobs(database_engine, factory)
    assert await restarted.work_once(interrupted) is True
    original = await runs.get(run.id)
    assert original.failure_code == "ANALYSIS_INTERRUPTED" and len(calls) == 1
    await portfolios.set_cash_balance(inp.portfolio_id, "22000")
    next_id = uuid4()
    new = await service.retry(run.id, next_id)
    again = await service.retry(run.id, next_id)
    assert new.id == again.id != original.id and new.status == "QUEUED"
    assert new.payload["retry_of"] == str(original.id)
    assert Decimal(new.payload["input_snapshot"]["portfolio"]["cash_balance"]) == Decimal("22000")
    assert (await runs.get(run.id)).payload == original.payload
    assert len(calls) == 1


async def test_exception_is_sanitized_and_history_is_database_protected(database_engine):
    factory, _, runs, _, port, service, inp = await jobs_setup(database_engine)
    run = await service.submit(uuid4(), inp)

    async def failed(request, progress):
        raise RuntimeError("synthetic-sensitive-error-never-display")

    assert await port.work_once(failed)
    result = await runs.get(run.id)
    assert result.failure_code == "ANALYSIS_EXECUTION_FAILED"
    assert "synthetic-sensitive-error" not in str(result)
    for statement in (
        update(AnalysisJobRecord).values(request_json={}),
        text("DELETE FROM analysis_job"),
        text("UPDATE analysis_progress SET stage='FAKE'"),
        text("DELETE FROM analysis_progress"),
    ):
        with pytest.raises(DBAPIError, match=r"immutable|append-only"):
            async with database_engine.begin() as connection:
                await connection.execute(statement)
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(AnalysisProgressRecord)) == 3
    await database_engine.dispose()
    with pytest.raises(RuntimeError, match="禁止删除"):
        await asyncio.to_thread(command.downgrade, Config("alembic.ini"), "20261015_0016")


async def test_submit_failure_rolls_back_run_queue_and_outbox(database_engine, monkeypatch):
    factory, _, _, _, port, service, inp = await jobs_setup(database_engine)

    async def fail(*args, **kwargs):
        raise RuntimeError("synthetic event failure")

    monkeypatch.setattr(port, "_event", fail)
    with pytest.raises(RuntimeError, match="synthetic event failure"):
        await service.submit(uuid4(), inp)
    async with factory() as session:
        for model in (AnalysisRunRecord, AnalysisJobRecord, AnalysisProgressRecord):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_evidence_expired_while_queued_never_calls_models(database_engine, monkeypatch):
    _, _, runs, _, port, service, inp = await jobs_setup(database_engine)
    run = await service.submit(uuid4(), inp)
    calls = []

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=400)

    async def forbidden(request, progress):
        calls.append(request)
        return AnalysisRunResult("SUCCEEDED", None)

    monkeypatch.setattr("investment_os.infrastructure.analysis_jobs.datetime", Later)
    assert await port.work_once(forbidden)
    assert calls == []
    assert (await runs.get(run.id)).failure_code == "ANALYSIS_EVIDENCE_UNAVAILABLE"


async def test_production_worker_composition_consumes_queue_and_persists_real_stages(
    database_engine,
    migrated_database_url,
    monkeypatch,
):
    _, _, runs, _, _, service, inp = await jobs_setup(database_engine)
    run = await service.submit(uuid4(), inp)
    calls = []

    class Gateway:
        async def complete(self, request):
            calls.append(request)
            value = json.loads(request.input_payload_json)
            return LLMGatewayResponse(
                provider="SYNTHETIC",
                model_name="fixture-only",
                latency_ms=1,
                input_tokens=10,
                output_tokens=20,
                raw_output=json.dumps(
                    {
                        "schema_version": "1.0",
                        "agent_role": request.role.value,
                        "instrument_id": value["instrument"]["instrument_id"],
                        "as_of": value["as_of"],
                        "stance": "NEUTRAL",
                        "confidence": "0.6",
                        "time_horizon": "DAYS",
                        "observations": [
                            {
                                "claim": "合成事实",
                                "evidence_ids": value["evidence_ids"][:1],
                                "materiality": "LOW",
                            }
                        ],
                        "thesis_impacts": [],
                        "assumptions": [],
                        "risks": [],
                        "invalidation_conditions": [],
                        "unknowns": [],
                        "requested_followups": [],
                    }
                ),
            )

        async def close(self):
            return None

    monkeypatch.setattr(
        "investment_os.infrastructure.analysis_worker.OpenAICompatibleLLMGateway",
        lambda **kwargs: Gateway(),
    )
    worker = AnalysisWorker(Settings(database_url=migrated_database_url))
    try:
        assert await worker.run_once()
        assert not await worker.run_once()
    finally:
        await worker.close()
    result = await runs.get(run.id)
    assert result.status == "SUCCEEDED" and len(calls) == 8
    assert {request.budget_task_id for request in calls} == {run.id}
    assert all(request.model_binding is not None for request in calls)
    assert result.payload["input_snapshot"] == run.payload["input_snapshot"]
    # Neutral synthetic specialists map to HOLD, never a new exposure.
    assert result.payload["decision"]["action"] == "HOLD"
    assert "MISSING_REFERENCE_QUOTES" in result.payload["failures"]


async def test_model_options_and_explicit_choice_are_frozen_with_stale_confirmation_rejected(
    database_engine,
):
    factory, _, runs, product, _, jobs, inp = await jobs_setup(database_engine)
    app = create_app(
        analysis_product_service=product,
        analysis_run_service=runs,
        analysis_job_service=jobs,
        write_api_token="synthetic-model-auth",
    )
    headers = {"Authorization": "Bearer synthetic-model-auth"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        choices = (await client.get("/api/v1/analysis-model-options")).json()
        assert len(choices["default_bindings"]) == 8 and "credential" not in json.dumps(choices)
        identity = choices["profiles"][0]["profile_id"]
        body = {
            "request_id": str(uuid4()),
            "instrument_id": str(inp.instrument_id),
            "portfolio_id": str(inp.portfolio_id),
            "model_profile_id": identity,
            "model_configuration_hash": choices["configuration_hash"],
        }
        response = await client.post("/api/v1/analysis-jobs", json=body, headers=headers)
        assert response.status_code == 202
        plan = response.json()["payload"]["input_snapshot"]["model_plan"]
        assert plan["selected_profile_id"] == identity and plan["mode"] == "SINGLE_PROFILE"
        assert all(b["profile"]["pricing_version"] == "synthetic-v1" for b in plan["bindings"])
        assert (await client.post("/api/v1/analysis-jobs", json=body, headers=headers)).json()[
            "id"
        ] == body["request_id"]
        async with factory() as session, session.begin():
            row = await session.get(ModelProviderProfileRecord, UUID(identity))
            row.max_tokens += 1
        # An already submitted request is not re-prepared or overwritten after settings changes.
        assert (await client.post("/api/v1/analysis-jobs", json=body, headers=headers)).json()[
            "payload"
        ]["input_snapshot"]["model_plan"] == plan
        stale = await client.post(
            "/api/v1/analysis-jobs", json={**body, "request_id": str(uuid4())}, headers=headers
        )
        assert (
            stale.status_code == 422
            and stale.json()["detail"] == "ANALYSIS_MODEL_CONFIGURATION_CHANGED"
        )
        conflict = await client.post(
            "/api/v1/analysis-jobs",
            json={**body, "model_profile_id": str(uuid4())},
            headers=headers,
        )
        assert conflict.status_code == 409
        invalid = await client.post(
            "/api/v1/analysis-jobs",
            json={
                **body,
                "request_id": str(uuid4()),
                "model_configuration_hash": None,
                "model_profile_id": str(uuid4()),
            },
            headers=headers,
        )
        assert invalid.status_code == 422


async def test_queued_changed_pricing_fails_before_models_and_snapshot_stays_immutable(
    database_engine,
):
    factory, _, runs, product, _, jobs, inp = await jobs_setup(database_engine)
    run = await jobs.submit(uuid4(), inp)
    frozen = run.payload["input_snapshot"]
    profile_id = UUID(frozen["model_plan"]["bindings"][0]["profile"]["profile_id"])
    async with factory() as session, session.begin():
        row = await session.get(ModelProviderProfileRecord, profile_id)
        row.input_token_price = Decimal("0.009")
    # The fixture has no committee: any attempt to execute a model would fail this assertion.
    assert product._committee is None
    assert await jobs.run_once()
    result = await runs.get(run.id)
    assert (
        result.status == "FAILED" and result.failure_code == "ANALYSIS_MODEL_CONFIGURATION_CHANGED"
    )
    assert result.payload["input_snapshot"] == frozen
    next_run = await jobs.retry(run.id, uuid4())
    assert next_run.id != run.id and next_run.payload["retry_of"] == str(run.id)
    assert (
        next_run.payload["input_snapshot"]["model_plan"]["bindings"][0]["profile"][
            "input_token_price"
        ]
        != frozen["model_plan"]["bindings"][0]["profile"]["input_token_price"]
    )


async def test_old_queued_input_without_model_plan_is_not_silently_bound_to_current_models(
    database_engine,
):
    _, _, _, product, _, _, inp = await jobs_setup(database_engine)
    prepared = await product.prepare(inp)
    result = await product.execute_prepared(replace(prepared.request, model_plan=None))
    assert (
        result.status == "FAILED" and result.failure_code == "ANALYSIS_MODEL_CONFIGURATION_MISSING"
    )


async def test_api_enqueues_without_running_models_and_requires_write_auth(database_engine):
    _, _, runs, product, port, service, inp = await jobs_setup(database_engine)
    app = create_app(
        analysis_product_service=product,
        analysis_run_service=runs,
        analysis_job_service=service,
        write_api_token="synthetic-job-auth",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as browser:
        body = {
            "request_id": str(uuid4()),
            "instrument_id": str(inp.instrument_id),
            "portfolio_id": str(inp.portfolio_id),
            "source": "RESEARCH",
            "evidence_ids": [str(item) for item in inp.evidence_ids],
        }
        assert (await browser.post("/api/v1/analysis-jobs", json=body)).status_code == 401
        headers = {"Authorization": "Bearer synthetic-job-auth"}
        response = await browser.post("/api/v1/analysis-jobs", json=body, headers=headers)
        assert response.status_code == 202
        run_id = response.json()["id"]
        assert response.json()["status"] == "QUEUED"
        assert (
            await browser.post(
                f"/api/v1/analysis-jobs/{run_id}/retry",
                json={"request_id": str(uuid4())},
                headers=headers,
            )
        ).status_code == 409
        rows = (await browser.get(f"/api/v1/analysis-runs/{run_id}/progress")).json()
        assert len(rows) == 1 and rows[0]["stage"] == "QUEUED"
        assert (await browser.post(f"/api/v1/analysis-jobs/{run_id}/cancel")).status_code == 401
        cancelled = await browser.post(f"/api/v1/analysis-jobs/{run_id}/cancel", headers=headers)
        assert cancelled.json()["status"] == "CANCELLED"
        assert (await browser.get(f"/api/v1/analysis-runs/{run_id}")).json()[
            "status"
        ] == "CANCELLED"
        assert len(await port.events(UUID(run_id))) == 2
