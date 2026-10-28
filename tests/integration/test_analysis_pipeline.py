"""Real PG/worker/gateway/budget composition; HTTP is explicitly synthetic MockTransport."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from analysis_fixture import model_output
from sqlalchemy import func, select
from test_analysis_runs_persistence import NoMarket, frozen_input, prepare

from investment_os.application.analysis_configuration import AnalysisStartService
from investment_os.application.instrument_catalog import InstrumentCatalogService
from investment_os.application.investment_analysis import InvestmentAnalysisOrchestrator
from investment_os.application.llm_budget import LLMBudgetPolicy, LLMBudgetService
from investment_os.application.portfolio_valuation import PortfolioValuationService
from investment_os.application.provider_settings import ProviderSettingsService
from investment_os.application.research_runtime import (
    DataProviderRuntimeRegistry,
    ResearchProviderRuntime,
)
from investment_os.infrastructure.analysis_execution import SqlAnalysisExecution
from investment_os.infrastructure.analysis_inputs import (
    AnalysisGatewayFactory,
    SqlAnalysisInputPreparer,
)
from investment_os.infrastructure.catalog_portfolio import SessionCatalogPort
from investment_os.infrastructure.evidence_ingestion import SqlAlchemyEvidenceIngestor
from investment_os.infrastructure.llm_budget import SqlAlchemyLLMBudgetStore
from investment_os.infrastructure.persistence.analysis_models import (
    AnalysisRoleOutputRecord,
    AnalysisShadowDecisionRecord,
)
from investment_os.infrastructure.persistence.models import (
    AgentRunRecord,
    CommitteeSessionRecord,
    FeatureSnapshotRecord,
)
from investment_os.infrastructure.portfolio_valuation import SqlValuationInputs
from investment_os.infrastructure.provider_settings import SqlAlchemyProviderSettingsStore
from investment_os.worker.analysis_runner import AnalysisWorkerRunner

pytestmark = pytest.mark.integration


class SyntheticSecrets:
    def __init__(self):
        self.values = {}

    async def put(self, key, value):
        self.values[key] = value

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)


async def stack(database_engine, *, invalid_role=None, evidence=True):
    sessions, store, queued = await prepare(database_engine)
    # Reuse the actual ingestion path, not a fabricated Evidence FK.
    frozen = await frozen_input(sessions, queued.command.request_id, queued)
    command = queued.command.model_copy(
        update={"evidence_ids": (frozen.evidence[0].evidence_id,) if evidence else ()}
    )
    secrets = SyntheticSecrets()
    providers = ProviderSettingsService(SqlAlchemyProviderSettingsStore(sessions), secrets)
    profile = await providers.save_model_profile(
        profile_id=None,
        name="声明合成模型",
        provider_type="OPENAI_COMPATIBLE",
        base_url="http://127.0.0.1:1/v1",
        model_name="synthetic-only",
        timeout_seconds=5,
        max_tokens=1000,
        enabled=True,
        credential="synthetic-not-a-real-key",
        pricing_version="synthetic-v1",
        pricing_currency="CNY",
        input_token_price=Decimal(0),
        output_token_price=Decimal(0),
        pricing_effective_at=datetime.now(UTC),
    )
    budget = LLMBudgetService(SqlAlchemyLLMBudgetStore(sessions))
    await budget.save_policy(
        LLMBudgetPolicy("synthetic-v1", "CNY", 2000000, 4000000, Decimal(1), Decimal(2))
    )
    command = command.model_copy(
        update={"model_profiles": {role: profile.id for role in command.model_profiles}}
    )
    calls = []

    async def respond(request):
        assert request.headers["Authorization"] == "Bearer synthetic-not-a-real-key"
        wrapper = json.loads(json.loads(request.content)["messages"][1]["content"])
        calls.append(wrapper)
        output = {"invalid": True} if wrapper["role"] == invalid_role else model_output(wrapper)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(output)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    research = ResearchProviderRuntime(
        provider_settings=providers, secret_store=secrets, registry=DataProviderRuntimeRegistry({})
    )
    execution = SqlAnalysisExecution(
        sessions,
        SqlAnalysisInputPreparer(
            sessions,
            store,
            providers,
            research,
            SqlAlchemyEvidenceIngestor(sessions, now=lambda: datetime.now(UTC)),
        ),
        AnalysisGatewayFactory(providers, secrets, budget, store, client=client),
    )
    service = AnalysisStartService(
        store,
        PortfolioValuationService(SqlValuationInputs(sessions), NoMarket()),
        providers,
        budget,
        InstrumentCatalogService(SessionCatalogPort(sessions)),
    )
    runner = AnalysisWorkerRunner(store, InvestmentAnalysisOrchestrator(store, execution))
    return sessions, store, providers, profile, budget, service, runner, command, calls, client


async def test_real_pipeline_links_artifacts_and_shared_run_budget_without_fake_sizing(
    database_engine,
):
    sessions, store, providers, _, budget, service, runner, command, calls, client = await stack(
        database_engine
    )
    try:
        queued = await service.start(command)
        await runner.dispatch_due()
        result = await store.get(queued.run_id)
        assert result.status.value == "DEGRADED", result.model_dump(mode="json")
        assert len(calls) == 9
        assert result.shadow_decision.action.value == "AVOID"
        assert result.shadow_decision.risk_gate == "UNKNOWN"
        assert (
            result.shadow_decision.target_quantity is result.shadow_decision.sizing_run_id is None
        )
        assert result.frozen_input.queued.command == command
        assert await providers.list_role_assignments() == []
        usage = await budget.usage()
        assert usage.input_tokens + usage.output_tokens == 270
        assert usage.reserved_tokens == 0
        async with sessions() as session:
            for model, count in [
                (AgentRunRecord, 9),
                (FeatureSnapshotRecord, 1),
                (CommitteeSessionRecord, 1),
                (AnalysisRoleOutputRecord, 9),
                (AnalysisShadowDecisionRecord, 1),
            ]:
                assert await session.scalar(select(func.count()).select_from(model)) == count
    finally:
        await client.aclose()


@pytest.mark.parametrize("mode", ["empty", "disabled", "budget", "invalid_cio"])
async def test_real_pipeline_failure_has_no_executable_shadow_or_silent_profile_fallback(
    database_engine, mode
):
    _, store, providers, profile, budget, service, runner, command, calls, client = await stack(
        database_engine,
        invalid_role="CIO" if mode == "invalid_cio" else None,
        evidence=mode != "empty",
    )
    try:
        queued = await service.start(command)
        if mode == "disabled":
            await providers._settings_port.save_model_profile(replace(profile, enabled=False))
        if mode == "budget":
            policy = await budget.policy()
            await budget.save_policy(replace(policy, version="changed"))
        await runner.dispatch_due()
        result = await store.get(queued.run_id)
        assert result.status.value == "FAILED", result.model_dump(mode="json")
        assert result.shadow_decision is None
        assert len(calls) == (11 if mode == "invalid_cio" else 0)
        assert await runner.dispatch_due() == {"claimed": 0, "interrupted": 0}
    finally:
        await client.aclose()


@pytest.mark.parametrize("window", ["after_preflight", "before_reservation_transaction"])
async def test_frozen_budget_change_at_final_reservation_blocks_egress_and_charges(
    database_engine, monkeypatch, window
):
    import asyncio

    from investment_os.infrastructure.persistence.models import (
        LLMBudgetReservationRecord,
        LLMUsageRecord,
    )

    (
        sessions,
        store,
        providers,
        profile,
        budget,
        service,
        runner,
        command,
        calls,
        client,
    ) = await stack(database_engine)
    await providers._settings_port.save_model_profile(
        replace(profile, input_token_price=Decimal("0.001"), output_token_price=Decimal("0.001"))
    )
    policy = await budget.policy()
    policy_a = replace(
        policy,
        task_cost_limit=Decimal(0) if window == "after_preflight" else Decimal("1000000"),
        daily_cost_limit=Decimal("1000000"),
    )
    # Same policy version is intentional: content, not only its label, must be pinned.
    policy_b = replace(
        policy_a, task_cost_limit=Decimal("1000000") if window == "after_preflight" else Decimal(0)
    )
    await budget.save_policy(policy_a)
    queued = await service.start(command)
    entered, release = asyncio.Event(), asyncio.Event()
    count = 0

    async def barrier():
        nonlocal count
        count += 1
        if count == 5:
            entered.set()
        await release.wait()

    if window == "after_preflight":
        original = store.step

        async def gate_step(*args, **kwargs):
            await original(*args, **kwargs)
            if kwargs["stage"] == "MODEL_CALL" and kwargs["status"] == "RUNNING":
                await barrier()

        monkeypatch.setattr(store, "step", gate_step)
    else:
        original = budget._port.reserve

        async def gate_reserve(**kwargs):
            await barrier()
            return await original(**kwargs)

        monkeypatch.setattr(budget._port, "reserve", gate_reserve)
    task = asyncio.create_task(runner.dispatch_due())
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        await budget.save_policy(policy_b)
        release.set()
        await asyncio.wait_for(task, timeout=10)
        assert calls == []
        result = await store.get(queued.run_id)
        assert result.status.value == "FAILED" and result.shadow_decision is None
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(LLMBudgetReservationRecord))
                == 0
            )
            assert await session.scalar(select(func.count()).select_from(LLMUsageRecord)) == 0
        usage = await budget.usage()
        assert usage.input_tokens == usage.output_tokens == usage.reserved_tokens == 0
        assert usage.total_cost == usage.reserved_cost == 0
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await client.aclose()


async def test_real_pipeline_keeps_future_and_expired_evidence_for_audit_only(database_engine):
    from datetime import timedelta

    from investment_os.application.research import ResearchArtifactDTO
    from investment_os.domain.values import UtcTimestamp

    sessions, store, _, _, _, service, runner, command, calls, client = await stack(database_engine)
    now = datetime.now(UTC)
    ids = []
    for state in ("future", "expired"):
        when = now + timedelta(hours=1) if state == "future" else now - timedelta(hours=2)
        expiry = now + timedelta(days=1) if state == "future" else now - timedelta(hours=1)
        saved = await SqlAlchemyEvidenceIngestor(sessions, now=lambda: now).ingest(
            ResearchArtifactDTO(
                provider="SYNTHETIC",
                provider_ref=state,
                artifact_type="NEWS",
                instrument_id=command.instrument_id,
                source_name="合成无效时点",
                source_locator=f"synthetic://{state}",
                source_tier="PRIMARY",
                observed_at=UtcTimestamp(when),
                effective_at=UtcTimestamp(when),
                available_at=UtcTimestamp(when),
                expires_at=UtcTimestamp(expiry),
                payload={"body": f"SYNTHETIC_{state.upper()}_BODY_NOT_FOR_MODEL"},
                source_schema_version="synthetic-v1",
            )
        )
        ids.append(saved.evidence_id)
    try:
        run = await service.start(
            command.model_copy(update={"evidence_ids": (*command.evidence_ids, *ids)})
        )
        await runner.dispatch_due()
        view = await store.get(run.run_id)
        assert view.status.value == "DEGRADED" and len(calls) == 9
        assert len(view.frozen_input.evidence) == 3
        body = json.dumps(calls)
        for item in view.frozen_input.evidence:
            if item.evidence_id in ids:
                assert item.freshness != "FRESH" and "NOT_FOR_MODEL" in item.payload_json
                assert str(item.evidence_id) not in body
        assert "NOT_FOR_MODEL" not in body
    finally:
        await client.aclose()


@pytest.mark.parametrize("window", ["credential", "reservation"])
async def test_frozen_model_disabled_across_await_has_zero_egress_and_no_budget_leak(
    database_engine, monkeypatch, window
):
    import asyncio

    from investment_os.infrastructure.persistence.models import (
        LLMBudgetReservationRecord,
        LLMUsageRecord,
    )

    (
        sessions,
        store,
        providers,
        profile,
        budget,
        service,
        runner,
        command,
        calls,
        client,
    ) = await stack(database_engine)
    queued = await service.start(command)
    entered, release = asyncio.Event(), asyncio.Event()
    count = 0

    async def barrier():
        nonlocal count
        count += 1
        if count == 5:
            entered.set()
        await release.wait()

    if window == "credential":
        original = providers._secret_store.get

        async def gated_get(identifier):
            result = await original(identifier)
            await barrier()
            return result

        monkeypatch.setattr(providers._secret_store, "get", gated_get)
    else:
        original = budget._port.reserve

        async def gated_reserve(**kwargs):
            result = await original(**kwargs)
            await barrier()
            return result

        monkeypatch.setattr(budget._port, "reserve", gated_reserve)

    task = asyncio.create_task(runner.dispatch_due())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await providers._settings_port.save_model_profile(replace(profile, enabled=False))
        release.set()
        await asyncio.wait_for(task, 10)
        assert calls == []
        result = await store.get(queued.run_id)
        assert result.status.value == "FAILED" and result.shadow_decision is None
        usage = await budget.usage()
        assert usage.input_tokens == usage.output_tokens == usage.reserved_tokens == 0
        assert usage.total_cost == usage.reserved_cost == 0
        async with sessions() as session:
            reservations = (await session.scalars(select(LLMBudgetReservationRecord))).all()
            assert len(reservations) == (5 if window == "reservation" else 0)
            assert all(item.status == "RELEASED_BEFORE_EGRESS" for item in reservations)
            assert await session.scalar(select(func.count()).select_from(LLMUsageRecord)) == 0
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await client.aclose()
