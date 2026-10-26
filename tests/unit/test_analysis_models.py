from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_openai_compatible_llm import MemoryProviderSettingsPort, MemorySecretStore

from investment_os.application.analysis_jobs import AnalysisWorkItem
from investment_os.application.analysis_models import (
    ANALYSIS_ROLES,
    AnalysisModelConfiguration,
    AnalysisModelPlan,
    FrozenModelProfile,
)
from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.provider_settings import (
    ModelProviderProfile,
    ProviderSettingsService,
    RoleModelAssignment,
)


def profile(**changes):
    return replace(
        ModelProviderProfile(
            id=uuid4(),
            name="合成模型",
            provider_type="OPENAI_COMPATIBLE",
            base_url="https://models.example.test/v1",
            model_name="synthetic-v1",
            credential_ref=uuid4(),
            timeout_seconds=30,
            max_tokens=2048,
            enabled=True,
            pricing_version="synthetic-pricing-v1",
            pricing_currency="USD",
            input_token_price=Decimal("0.000001"),
            output_token_price=Decimal("0.000002"),
        ),
        **changes,
    )


def setup():
    port = MemoryProviderSettingsPort()
    first, second = profile(), profile(name="另一个合成模型", model_name="synthetic-v2")
    port.models = {p.id: p for p in (first, second)}
    port.assignments = {"DEFAULT": RoleModelAssignment("DEFAULT", first.id)}
    service = ProviderSettingsService(port, MemorySecretStore())
    return port, AnalysisModelConfiguration(service), first, second


async def test_default_models_are_frozen_and_later_role_mapping_does_not_replace_them():
    port, config, first, second = setup()
    options = await config.options()
    plan = await config.freeze(None, options.configuration_hash)
    port.assignments["DEFAULT"] = RoleModelAssignment("DEFAULT", second.id)
    await config.validate(plan)
    assert {b.profile.profile_id for b in plan.bindings} == {first.id}
    assert {b.role for b in plan.bindings} == set(ANALYSIS_ROLES)
    assert {b.profile.pricing_version for b in plan.bindings} == {"synthetic-pricing-v1"}
    assert {b.profile.input_token_price for b in plan.bindings} == {Decimal("0.000001")}
    assert str(first.credential_ref) not in plan.model_dump_json()
    assert "credential" not in plan.model_dump_json() and "base_url" not in plan.model_dump_json()
    assert AnalysisModelPlan.model_validate_json(plan.model_dump_json()) == plan
    assert (
        "model_plan"
        in AnalysisWorkItem.model_json_schema()["$defs"]["AnalysisRequest"]["properties"]
    )


async def test_explicit_single_profile_is_complete_without_changing_global_assignments():
    port, config, first, second = setup()
    plan = await config.freeze(second.id, None)
    assert plan.mode == "SINGLE_PROFILE" and plan.selected_profile_id == second.id
    assert all(b.profile.profile_id == second.id for b in plan.bindings)
    assert port.assignments["DEFAULT"].model_provider_profile_id == first.id


@pytest.mark.parametrize(
    "change",
    [
        {"enabled": False},
        {"model_name": "changed"},
        {"base_url": "https://other.example.test/v1"},
        {"input_token_price": Decimal("0.005")},
        {"pricing_version": "new-version"},
        {"max_tokens": 4096},
        {"timeout_seconds": 5},
        {"credential_ref": None},
    ],
)
async def test_changed_or_disabled_model_plan_fails_closed(change):
    port, config, first, _ = setup()
    plan = await config.freeze(None, None)
    port.models[first.id] = replace(first, **change)
    with pytest.raises(ApplicationError) as caught:
        await config.validate(plan)
    assert caught.value.code == ApplicationErrorCode.ANALYSIS_MODEL_CONFIGURATION_CHANGED


async def test_deleted_model_fails_closed_but_credential_rotation_does_not_copy_old_secret():
    port, config, first, _ = setup()
    plan = await config.freeze(None, None)
    port.models[first.id] = replace(first, credential_ref=uuid4())
    await config.validate(plan)
    del port.models[first.id]
    with pytest.raises(ApplicationError):
        await config.validate(plan)


async def test_confirmation_rejects_stale_choices_and_missing_role_does_not_fall_back():
    port, config, first, second = setup()
    old = await config.options()
    port.assignments["RISK"] = RoleModelAssignment("RISK", second.id)
    with pytest.raises(ApplicationError) as caught:
        await config.freeze(None, old.configuration_hash)
    assert caught.value.code == ApplicationErrorCode.ANALYSIS_MODEL_CONFIGURATION_CHANGED
    port.models[second.id] = replace(second, enabled=False)
    options = await config.options()
    assert options.missing_roles == (ANALYSIS_ROLES[-1],)
    with pytest.raises(ApplicationError):
        await config.freeze(None, None)
    with pytest.raises(ApplicationError):
        await config.freeze(second.id, None)
    assert len((await config.freeze(first.id, None)).bindings) == 8


async def test_plan_rejects_missing_duplicate_and_mismatched_role_bindings():
    _, config, _, second = setup()
    plan = await config.freeze(None, None)
    for bindings in (plan.bindings[:-1], (*plan.bindings[:-1], plan.bindings[0])):
        with pytest.raises(ValidationError):
            AnalysisModelPlan(mode="ROLE_MAPPING", bindings=bindings)
    with pytest.raises(ValidationError):
        AnalysisModelPlan(
            mode="SINGLE_PROFILE", selected_profile_id=second.id, bindings=plan.bindings
        )
    with pytest.raises(ValidationError):
        plan.bindings[0].profile.model_name = "overwrite"
    assert (
        FrozenModelProfile.capture(second).configuration_hash
        != plan.bindings[0].profile.configuration_hash
    )
