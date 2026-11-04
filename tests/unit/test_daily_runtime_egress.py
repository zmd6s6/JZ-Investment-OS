"""Legacy identity and actual OpenAI egress admission remain fail-closed across awaits."""

import asyncio
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from test_analysis_orchestration import Store, inputs
from test_openai_compatible_llm import MemoryBudgetPort, MemorySecretStore, _request

from investment_os.application.analysis_configuration import budget_hash, profile_hash
from investment_os.application.analysis_runs import (
    AnalysisFrozenInput,
    AnalysisStart,
    SelectedModel,
)
from investment_os.application.llm_budget import LLMBudgetService
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.application.provider_settings import ModelProviderProfile
from investment_os.application.runtime_authorization import (
    RuntimeAuthorizationRef,
    RuntimeEgressBlocked,
)
from investment_os.infrastructure.analysis_inputs import (
    AnalysisGatewayFactory,
    PinnedAnalysisGateway,
    PinnedModelResolver,
    SqlAnalysisInputPreparer,
)
from investment_os.infrastructure.openai_compatible_llm import OpenAICompatibleLLMGateway


def reference():
    return RuntimeAuthorizationRef(
        kind="DAILY_SHADOW",
        schedule_id=uuid4(),
        revision_id=uuid4(),
        authorization_version=2,
        authorization_hash="a" * 64,
        intent_id=uuid4(),
    )


async def test_absent_runtime_marker_preserves_legacy_command_and_frozen_input_hashes():
    _, queued, frozen = await inputs()
    original = queued.command.model_dump(mode="json")
    assert "runtime_authorization" not in original
    explicit = AnalysisStart.model_validate({**original, "runtime_authorization": None})
    assert explicit.model_dump(mode="json") == original
    assert fingerprint(explicit.model_dump(mode="json")) == fingerprint(original)
    raw = frozen.model_dump(mode="json")
    raw["queued"]["command"]["runtime_authorization"] = None
    restored = AnalysisFrozenInput.model_validate(raw)
    assert restored.model_dump(mode="json") == frozen.model_dump(mode="json")
    assert (
        fingerprint(restored.model_dump(mode="json", exclude={"input_hash"})) == frozen.input_hash
    )
    tagged = AnalysisStart.model_validate(
        {**original, "runtime_authorization": reference().model_dump(mode="json")}
    )
    assert fingerprint(tagged.model_dump(mode="json")) != fingerprint(original)


@pytest.mark.parametrize(
    "patch",
    [
        {"kind": "LIVE"},
        {"authorization_version": True},
        {"authorization_version": 0},
        {"authorization_hash": "not-a-hash"},
        {"auto_trade": True},
    ],
)
def test_scheduled_reference_is_strict_and_cannot_invent_execution_permission(patch):
    with pytest.raises(ValidationError):
        RuntimeAuthorizationRef.model_validate({**reference().model_dump(mode="json"), **patch})


async def test_missing_authorization_module_blocks_scheduled_input_and_model_factory_before_io():
    run_id, queued, _ = await inputs()
    marker = reference().model_copy(update={"intent_id": queued.command.request_id})
    queued = queued.model_copy(
        update={"command": queued.command.model_copy(update={"runtime_authorization": marker})}
    )
    calls = []

    def reject(request):
        calls.append(request)
        raise AssertionError("no HTTP allowed")

    async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
        factory = AnalysisGatewayFactory(None, None, None, None, client=client)
        with pytest.raises(ValueError, match="DAILY_AUTHORIZATION_MODULE_UNAVAILABLE"):
            factory.gateway_for(run_id, uuid4(), queued)
    preparer = SqlAnalysisInputPreparer(None, None, None, None, None)
    with pytest.raises(ValueError, match="DAILY_AUTHORIZATION_MODULE_UNAVAILABLE"):
        await preparer.prepare(run_id, uuid4(), queued)
    assert calls == []


@pytest.mark.parametrize("window", ["credential", "reservation"])
async def test_runtime_deadline_checked_after_await_before_http_releases_only_unstarted_budget(
    window,
):
    entered, release = asyncio.Event(), asyncio.Event()
    state = {"expired": False}
    profile = ModelProviderProfile(
        uuid4(),
        "synthetic",
        "OPENAI_COMPATIBLE",
        "https://synthetic.invalid/v1",
        "synthetic",
        uuid4(),
        10,
        500,
        True,
        "TEST",
        "USD",
        Decimal("0.01"),
        Decimal("0.02"),
    )

    class Profiles:
        async def get_model_profile(self, identifier):
            return profile

    class Secrets(MemorySecretStore):
        async def get(self, identifier):
            if window == "credential":
                entered.set()
                await release.wait()
            return "synthetic-only"

    class Budgets(MemoryBudgetPort):
        def __init__(self):
            super().__init__()
            self.reservations = []
            self.released = []
            self.reconciled = []

        async def reserve(self, **values):
            reservation = await super().reserve(**values)
            self.reservations.append(reservation)
            if window == "reservation":
                entered.set()
                await release.wait()
            return reservation

        async def release_before_egress(self, reservation):
            self.released.append(reservation)

        async def reconcile(self, reservation, **values):
            self.reconciled.append(reservation)

    budgets, profiles, store = Budgets(), Profiles(), Store()
    run_id, queued, _ = await inputs()
    queued = queued.model_copy(
        update={
            "budget_hash": budget_hash(budgets.policy),
            "models": {
                role: SelectedModel(
                    profile_id=profile.id,
                    name=profile.name,
                    model_name=profile.model_name,
                    config_hash=profile_hash(profile),
                    timeout_seconds=10,
                    max_tokens=500,
                )
                for role in queued.models
            },
        }
    )
    resolver = PinnedModelResolver(profiles, queued)
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    def final_check():
        if state["expired"]:
            raise RuntimeEgressBlocked("DAILY_AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        budget = LLMBudgetService(budgets)
        delegate = OpenAICompatibleLLMGateway(
            provider_settings=resolver,
            secret_store=Secrets(),
            budget_service=budget,
            client=client,
            before_egress=final_check,
        )
        gateway = PinnedAnalysisGateway(resolver, budget, queued, delegate, store, run_id, uuid4())
        task = asyncio.create_task(gateway.complete(_request()))
        await asyncio.wait_for(entered.wait(), 2)
        state["expired"] = True
        release.set()
        outcome = (await asyncio.gather(task, return_exceptions=True))[0]
    assert isinstance(outcome, RuntimeEgressBlocked)
    assert calls == [] and budgets.reconciled == []
    assert budgets.released == budgets.reservations
    assert len(budgets.reservations) == (1 if window == "reservation" else 0)
    assert store.steps[-1]["reason_code"] == "DAILY_AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID"
    assert store.steps[-1]["payload"]["egress"] is False
    assert store.steps[-1]["payload"]["cost_unconfirmed"] is False
