"""Actual SQL state provenance, historical replay and no inferred transitions."""

from datetime import timedelta
from uuid import uuid4

import pytest
import test_opportunity_funnel as fixture
from sqlalchemy import select

from investment_os.infrastructure.opportunity_lifecycle import SqlOpportunityLifecycle
from investment_os.infrastructure.persistence.models import (
    InstrumentStateRecord,
    InvestmentThesisRecord,
    ThesisVersionRecord,
)
from investment_os.worker.weekly_funnel import weekly_worker

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "kind,reason",
    [
        ("missing", "STATE_NOT_PROVIDED"),
        ("future", "STATE_NOT_YET_AVAILABLE"),
        ("recorded_later", "STATE_NOT_YET_AVAILABLE"),
        ("revised", "STATE_HISTORY_UNAVAILABLE"),
        ("invalid", "STATE_INVALID"),
        ("broken_reference", "STATE_INVALID"),
        ("normal", "RECORDED_INITIAL_STATE"),
    ],
)
async def test_state_missing_future_revised_invalid_and_valid_do_not_infer_candidate_state(
    database_engine, kind, reason
):
    sessions, _, _, _, query = await fixture.setup(database_engine, count=2)
    identifier = query.instrument_ids[0]
    if kind != "missing":
        async with sessions() as session, session.begin():
            thesis_version = None
            if kind == "broken_reference":
                thesis_id, thesis_version = uuid4(), uuid4()
                session.add(
                    InvestmentThesisRecord(
                        id=thesis_id,
                        instrument_id=query.instrument_ids[1],
                        status="ACTIVE",
                        created_by="synthetic",
                        correlation_id=uuid4(),
                    )
                )
                await session.flush()
                session.add(
                    ThesisVersionRecord(
                        id=thesis_version,
                        thesis_id=thesis_id,
                        version=1,
                        thesis_state="UNKNOWN",
                        summary="synthetic unrelated thesis",
                        pillars_json={},
                        catalysts_json={},
                        risks_json={},
                        invalidation_conditions_json={},
                        monitoring_conditions_json={},
                        change_reason="HUMAN_CORRECTION",
                        content_hash="a" * 64,
                        created_at=fixture.NOW,
                        created_by="synthetic",
                        correlation_id=uuid4(),
                    )
                )
                await session.flush()
            session.add(
                InstrumentStateRecord(
                    instrument_id=identifier,
                    lifecycle_state="NOT_A_STATE" if kind == "invalid" else "WATCH",
                    effective_at=fixture.NOW + timedelta(seconds=1)
                    if kind == "future"
                    else fixture.NOW,
                    created_at=fixture.NOW + timedelta(seconds=1)
                    if kind == "recorded_later"
                    else fixture.NOW,
                    version=2 if kind == "revised" else 1,
                    thesis_version_id=thesis_version,
                    created_by="synthetic",
                    correlation_id=uuid4(),
                )
            )
    snapshot = await SqlOpportunityLifecycle(sessions).read_lifecycle(identifier, fixture.NOW)
    assert snapshot.reason == reason
    assert snapshot.status == ("AVAILABLE" if kind == "normal" else "UNKNOWN")
    assert snapshot.state == ("WATCH" if kind == "normal" else None)
    assert snapshot.source_hash == (snapshot.fingerprint() if kind == "normal" else None)


async def test_production_funnel_freezes_state_without_writing_or_recomputing_old_history(
    database_engine,
):
    sessions, store, _, commands, query = await fixture.setup(database_engine)
    service = weekly_worker(sessions, now=lambda: fixture.NOW).service
    for command in commands:
        await service.save_facts(command)
    identifier = query.instrument_ids[0]
    async with sessions() as session, session.begin():
        session.add(
            InstrumentStateRecord(
                instrument_id=identifier,
                lifecycle_state="WATCH",
                version=1,
                created_at=fixture.NOW,
                effective_at=fixture.NOW,
                created_by="synthetic",
                correlation_id=uuid4(),
            )
        )
    run = await service.run(query)
    row = run.rows[0]
    assert row.candidate and row.lifecycle_state == "WATCH"
    assert row.lifecycle_snapshot and row.lifecycle_snapshot.source_version == 1
    assert row.next_condition == "EXPLICIT_RESEARCH_CONSENT_REQUIRED"
    frozen = run.model_dump(mode="json")
    async with sessions() as session, session.begin():
        state = await session.scalar(select(InstrumentStateRecord))
        assert state and state.lifecycle_state == "WATCH" and state.version == 1
        state.lifecycle_state = "SETUP"
        state.version = 2
    assert (await service.run(query)).model_dump(mode="json") == frozen
    assert (await store.get_run(run.run_id)).model_dump(mode="json") == frozen
    new = await service.run(query.model_copy(update={"request_id": uuid4()}))
    assert new.rows[0].lifecycle_state is None
    assert new.rows[0].lifecycle_snapshot.reason == "STATE_HISTORY_UNAVAILABLE"
    assert new.candidate_ids == run.candidate_ids


async def test_complete_and_production_weekly_keep_original_state_snapshot(database_engine):
    import test_complete_weekly as weekly_fixture

    from investment_os.application.complete_scope import CompleteScopeService
    from investment_os.infrastructure.complete_weekly import CompleteWeeklyRunner

    sessions, store, _, config, _, scope = await weekly_fixture.setup(database_engine, count=2)
    identifier = config.template.instrument_ids[0]
    async with sessions() as session, session.begin():
        session.add(
            InstrumentStateRecord(
                instrument_id=identifier,
                lifecycle_state="DISCOVER",
                version=1,
                created_at=fixture.NOW,
                effective_at=fixture.NOW,
                created_by="synthetic",
                correlation_id=uuid4(),
            )
        )
    production = weekly_worker(sessions, now=lambda: weekly_fixture.NOW)
    complete = CompleteScopeService(scope, production.service, now=lambda: weekly_fixture.NOW)
    runner = CompleteWeeklyRunner(sessions, complete)
    await weekly_fixture.enable(store, config)
    await runner.dispatch_due(now=weekly_fixture.NOW)
    result = (await store.overview()).recent_runs[0]
    frozen = await scope.get_complete(result.funnel_run_id)
    assert frozen
    row = next(r for r in frozen.rows if r.instrument_id == identifier)
    assert row.lifecycle_state == "DISCOVER" and row.lifecycle_snapshot.status == "AVAILABLE"
    assert row.lifecycle_snapshot.as_of == frozen.effective_as_of
    assert any(
        r.lifecycle_snapshot.status == "UNKNOWN"
        for r in frozen.rows
        if r.instrument_id != identifier
    )
    assert await runner.dispatch_due(now=weekly_fixture.NOW) == ()
    assert await scope.get_complete(result.funnel_run_id) == frozen
