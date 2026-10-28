"""Final research adapter construction must use the explicitly frozen profile."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
from test_analysis_orchestration import Store, inputs

from investment_os.application.analysis_configuration import profile_hash
from investment_os.application.analysis_runs import SelectedData
from investment_os.application.provider_settings import DataProviderProfile
from investment_os.application.research_runtime import (
    DataProviderRuntimeRegistry,
    ResearchProviderRuntime,
)
from investment_os.infrastructure.analysis_inputs import SqlAnalysisInputPreparer


@pytest.mark.parametrize("change", ["endpoint", "provider", "retention", "disabled"])
@pytest.mark.parametrize("window", ["before_runtime", "during_credential"])
async def test_research_profile_drift_at_final_factory_never_changes_provider_or_sends(
    change, window
):
    run_id, queued, _ = await inputs()
    profile = DataProviderProfile(
        uuid4(), "synthetic-A", "BOCHA_WEB_SEARCH", "https://a.example.test", uuid4(), 10, True, 30
    )
    changed = replace(
        profile,
        **{
            "endpoint": {"base_url": "https://b.example.test"},
            "provider": {"provider_type": "SYNTHETIC_OTHER"},
            "retention": {"retention_days": 90},
            "disabled": {"enabled": False},
        }[change],
    )
    entered, release = asyncio.Event(), asyncio.Event()
    factories = []

    class Profiles:
        current = profile

        async def get_data_profile(self, identifier):
            return self.current

    class Secrets:
        async def get(self, identifier):
            if window == "during_credential":
                entered.set()
                await release.wait()
            return "synthetic-credential"

    class Provider:
        async def fetch_artifacts(self, request):
            return []

    def factory(selected, credential):
        factories.append(selected)
        return Provider()

    class GatedStore(Store):
        async def step(self, *args, **kwargs):
            await super().step(*args, **kwargs)
            if (
                window == "before_runtime"
                and kwargs["stage"] == "RESEARCH"
                and kwargs["status"] == "RUNNING"
            ):
                entered.set()
                await release.wait()

    profiles, store = Profiles(), GatedStore()
    runtime = ResearchProviderRuntime(
        provider_settings=profiles,
        secret_store=Secrets(),
        registry=DataProviderRuntimeRegistry(
            {"BOCHA_WEB_SEARCH": factory, "SYNTHETIC_OTHER": factory}
        ),
    )
    queued = queued.model_copy(
        update={
            "command": queued.command.model_copy(
                update={
                    "data_profile_ids": (profile.id,),
                    "query": "synthetic",
                    "allow_data_calls": True,
                }
            ),
            "data_profiles": (
                SelectedData(
                    profile_id=profile.id,
                    name=profile.name,
                    provider_type=profile.provider_type,
                    config_hash=profile_hash(profile),
                ),
            ),
        }
    )
    prepare = SqlAnalysisInputPreparer(None, store, profiles, runtime, None)
    task = asyncio.create_task(prepare.prepare(run_id, uuid4(), queued))
    await asyncio.wait_for(entered.wait(), timeout=1)
    profiles.current = changed
    release.set()
    outcome = (await asyncio.gather(task, return_exceptions=True))[0]
    assert factories == []
    assert isinstance(outcome, ValueError) and str(outcome) == "ANALYSIS_DATA_PROFILE_CHANGED"


async def test_unchanged_frozen_research_profile_uses_exact_selected_adapter():
    from datetime import UTC, datetime

    from investment_os.application.research import ResearchRequest
    from investment_os.domain.values import UtcTimestamp

    profile = DataProviderProfile(
        uuid4(), "synthetic", "SYNTHETIC", "https://a.example.test", uuid4(), 10, True, 30
    )
    selected = []

    class Profiles:
        async def get_data_profile(self, identifier):
            assert identifier == profile.id
            return profile

    class Secrets:
        async def get(self, identifier):
            assert identifier == profile.credential_ref
            return "synthetic-credential"

    class Provider:
        async def fetch_artifacts(self, request):
            return []

    def factory(actual, credential):
        selected.append(actual)
        return Provider()

    runtime = ResearchProviderRuntime(
        provider_settings=Profiles(),
        secret_store=Secrets(),
        registry=DataProviderRuntimeRegistry({"SYNTHETIC": factory}),
    )
    assert (
        await runtime.fetch(
            profile_id=profile.id,
            expected_profile_hash=profile_hash(profile),
            request=ResearchRequest((), UtcTimestamp(datetime.now(UTC)), query="synthetic"),
        )
        == []
    )
    assert selected == [profile]
