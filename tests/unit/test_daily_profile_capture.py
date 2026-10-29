"""Profile capture is SQL-only and never obtains credentials or performs HTTP."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_daily_runtime_contract import NOW, draft

from investment_os.application.analysis_runs import ANALYSIS_ROLES
from investment_os.application.daily_runtime import DailyError, DailySave
from investment_os.application.llm_budget import LLMBudgetPolicy
from investment_os.application.provider_settings import ModelProviderProfile
from investment_os.infrastructure.daily_runtime_setup import SqlDailySetup


def fixture():
    profile = ModelProviderProfile(
        id=uuid4(),
        name="synthetic local model",
        provider_type="OPENAI_COMPATIBLE",
        base_url="http://127.0.0.1:18121/v1",
        model_name="synthetic",
        credential_ref=uuid4(),
        timeout_seconds=10,
        max_tokens=100,
        enabled=True,
        pricing_version="synthetic-v1",
        pricing_currency="USD",
        input_token_price=Decimal("0.001"),
        output_token_price=Decimal("0.002"),
        pricing_effective_at=NOW - timedelta(days=1),
    )
    policy = LLMBudgetPolicy(
        version="synthetic-v1",
        currency="USD",
        task_token_limit=1000,
        daily_token_limit=2000,
        task_cost_limit=Decimal("1"),
        daily_cost_limit=Decimal("2"),
    )
    state = SimpleNamespace(profile=profile, policy=policy, profile_reads=0, budget_reads=0)

    async def get_profile(identifier):
        state.profile_reads += 1
        assert identifier == profile.id
        return state.profile

    async def get_policy():
        state.budget_reads += 1
        return state.policy

    setup = SqlDailySetup(
        None, SimpleNamespace(get_model_profile=get_profile), SimpleNamespace(policy=get_policy)
    )
    command = DailySave(
        **{
            **draft(),
            "mode": "SCHEDULED_SHADOW",
            "model_profiles": {role: profile.id for role in ANALYSIS_ROLES},
            "evidence_source_names": ("synthetic",),
            "limits": dict(
                currency="USD", task_tokens=1000, day_tokens=2000, task_cost="1", day_cost="2"
            ),
            "local_only_acknowledgement": False,
            "model_egress_acknowledgement": True,
            "cost_acknowledgement": True,
        },
        request_id=uuid4(),
        schedule_id=uuid4(),
        expected_version=0,
    )
    return setup, state, command


async def test_daily_profile_capture_has_exact_complete_roles_prices_destination_and_budget():
    setup, state, command = fixture()
    models, prices, budget, snapshot = await setup.capture_profiles(command, NOW)
    assert set(models) == set(prices) == set(ANALYSIS_ROLES)
    assert state.profile_reads == 1 and state.budget_reads == 1
    assert all(value.profile_id == state.profile.id for value in models.values())
    assert all(
        value.base_url == state.profile.base_url and value.input_token_price == "0.001"
        for value in prices.values()
    )
    assert len(budget) == 64 and snapshot.limits.task_cost == "1"


async def test_daily_local_mode_never_even_reads_a_provider_or_budget():
    setup, state, _ = fixture()
    command = DailySave(**draft(), request_id=uuid4(), schedule_id=uuid4(), expected_version=0)
    assert await setup.capture_profiles(command, NOW) == ({}, {}, None, None)
    assert state.profile_reads == state.budget_reads == 0


@pytest.mark.parametrize(
    "patch",
    [
        dict(enabled=False),
        dict(credential_ref=None),
        dict(provider_type="UNSUPPORTED"),
        dict(pricing_currency="CNY"),
        dict(pricing_version=None),
        dict(input_token_price=None),
        dict(input_token_price=Decimal("NaN")),
        dict(output_token_price=Decimal("-0.1")),
        dict(pricing_effective_at=NOW + timedelta(seconds=1)),
        dict(max_tokens=1001),
        dict(base_url="https://synthetic.invalid/v1?credential=unusable"),
    ],
)
async def test_incomplete_disabled_changed_or_unpriced_model_cannot_obtain_daily_permission(patch):
    setup, state, command = fixture()
    state.profile = replace(state.profile, **patch)
    with pytest.raises(ValueError):
        await setup.capture_profiles(command, NOW)


@pytest.mark.parametrize(
    "patch",
    [
        dict(currency="CNY"),
        dict(task_token_limit=1001),
        dict(daily_token_limit=2001),
        dict(task_cost_limit=Decimal("1.01")),
        dict(daily_cost_limit=Decimal("2.01")),
    ],
)
async def test_saved_budget_above_explicit_daily_cost_or_token_cap_is_fail_closed(patch):
    setup, state, command = fixture()
    state.policy = replace(state.policy, **patch)
    with pytest.raises(DailyError, match="DAILY_BUDGET_EXCEEDS_AUTHORIZATION"):
        await setup.capture_profiles(command, NOW)
    assert state.profile_reads == 0
