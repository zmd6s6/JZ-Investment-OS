"""Frozen models cannot drift across credential or budget await boundaries."""

import asyncio
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from test_analysis_orchestration import Store, inputs
from test_openai_compatible_llm import MemoryBudgetPort, MemorySecretStore, _request

from investment_os.application.analysis_configuration import budget_hash, profile_hash
from investment_os.application.analysis_runs import SelectedModel
from investment_os.application.llm_budget import LLMBudgetService
from investment_os.application.provider_settings import ModelProviderProfile
from investment_os.infrastructure.analysis_inputs import PinnedAnalysisGateway, PinnedModelResolver
from investment_os.infrastructure.openai_compatible_llm import (
    ModelProfileChanged,
    OpenAICompatibleLLMGateway,
)


@pytest.mark.parametrize("window", ["credential", "reservation"])
@pytest.mark.parametrize("change", ["disabled", "endpoint", "model", "credential", "pricing"])
async def test_model_profile_drift_never_sends_and_releases_only_unstarted_reservation(
    window, change
):
    entered, release = asyncio.Event(), asyncio.Event()
    profile = ModelProviderProfile(
        uuid4(),
        "synthetic",
        "OPENAI_COMPATIBLE",
        "https://a.example.test/v1",
        "synthetic-A",
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
        current = profile

        async def get_model_profile(self, identifier):
            return self.current

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

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        budget = LLMBudgetService(budgets)
        delegate = OpenAICompatibleLLMGateway(
            provider_settings=resolver, secret_store=Secrets(), budget_service=budget, client=client
        )
        gateway = PinnedAnalysisGateway(resolver, budget, queued, delegate, store, run_id, uuid4())
        task = asyncio.create_task(gateway.complete(_request()))
        await asyncio.wait_for(entered.wait(), 2)
        profiles.current = replace(
            profile,
            **{
                "disabled": {"enabled": False},
                "endpoint": {"base_url": "https://b.example.test/v1"},
                "model": {"model_name": "synthetic-B"},
                "credential": {"credential_ref": uuid4()},
                "pricing": {"input_token_price": Decimal("0.03")},
            }[change],
        )
        release.set()
        outcome = (await asyncio.gather(task, return_exceptions=True))[0]
    assert isinstance(outcome, ModelProfileChanged)
    assert calls == [] and budgets.reconciled == []
    assert budgets.released == budgets.reservations
    assert len(budgets.reservations) == (1 if window == "reservation" else 0)
    assert store.steps[-1]["reason_code"] == "ANALYSIS_MODEL_PROFILE_CHANGED"
    assert store.steps[-1]["payload"]["egress"] is False
    assert store.steps[-1]["payload"]["cost_unconfirmed"] is False


async def test_unchanged_frozen_model_preserves_real_gateway_usage():
    from test_openai_compatible_llm import _configured_gateway

    gateway, _service, profile = await _configured_gateway(
        handler=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "{}"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            )
        )
    )
    response = await gateway.complete(_request(expected_model_profile_hash=profile_hash(profile)))
    assert response.input_tokens == 1 and response.total_cost == Decimal("0.000003")
