"""Actual PG weekly audit paging, original revisions, isolated protocols and zero writes."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import event, select, text
from test_complete_weekly import enable as enable_complete
from test_complete_weekly import setup as setup_complete
from test_weekly_local_funnel import MONDAY
from test_weekly_local_funnel import enable as enable_local
from test_weekly_local_funnel import setup as setup_local

from investment_os.api.app import create_app
from investment_os.application.complete_weekly import CompleteWeeklyService
from investment_os.application.opportunities import OpportunityError
from investment_os.application.opportunity_schedule import WeeklyService
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.infrastructure.opportunity_schedule import WeeklyFunnelRunner, revision_payload
from investment_os.infrastructure.persistence.models import TaskRunRecord
from investment_os.infrastructure.weekly_funnel_models import (
    WeeklyMemberRecord,
    WeeklyResultRecord,
    WeeklyRevisionRecord,
)
from investment_os.infrastructure.weekly_task_history import SqlWeeklyTaskHistory

pytestmark = pytest.mark.integration
TOKEN = "synthetic-weekly-history-only"


async def seed_history(engine, monkeypatch, protocol="1.0", count=52):
    if protocol == "1.0":
        sessions, service, store, command, config, _ = await setup_local(engine, monkeypatch)
        await enable_local(store, config)
        await WeeklyFunnelRunner(sessions, service).dispatch_due(now=MONDAY)
    else:
        sessions, store, command, config, runner, _ = await setup_complete(engine, 2)
        await enable_complete(store, config)
        await runner.dispatch_due(now=datetime(2026, 11, 16, tzinfo=UTC))
    seeded = await append_history(sessions, config, command, protocol, count)
    return sessions, store, config, seeded


async def append_history(sessions, config, command, protocol, count=52, include_legacy_other=True):
    prefix = "weekly-local" if protocol == "1.0" else "weekly-complete"
    key_prefix = "weekly-funnel" if protocol == "1.0" else "weekly-complete"
    other_prefix = "weekly-complete" if protocol == "1.0" else "weekly-local"
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    seeded = []
    async with sessions() as session, session.begin():
        original = await session.get(WeeklyRevisionRecord, config.revision_id)
        members = tuple(
            await session.scalars(
                select(WeeklyMemberRecord.instrument_id).where(
                    WeeklyMemberRecord.revision_id == original.id
                )
            )
        )
        for index in range(count):
            identifier = uuid4()
            revision = WeeklyRevisionRecord(
                id=uuid4(),
                schedule_id=original.schedule_id,
                name=f"SEEDED_OLD_REVISION_{index}",
                venue=original.venue,
                calendar_import_id=original.calendar_import_id,
                calendar_hash=original.calendar_hash,
                coverage_start=original.coverage_start,
                coverage_end=original.coverage_end,
                template_run_id=original.template_run_id,
                template_json=original.template_json,
                content_hash="0" * 64,
                created_by="synthetic_history_seed",
                correlation_id=identifier,
                schema_version=protocol,
                metadata_json={},
            )
            revision.content_hash = fingerprint(revision_payload(revision))
            session.add(revision)
            await session.flush()
            session.add_all(
                [
                    WeeklyMemberRecord(revision_id=revision.id, instrument_id=member)
                    for member in members
                ]
            )
            task = TaskRunRecord(
                id=identifier,
                task_name=f"{prefix}:{config.schedule_id}",
                scheduled_for=stamp,
                status="SUCCEEDED" if index == 0 else "FAILED",
                attempt=1 if index == 0 else 3,
                idempotency_key=f"{key_prefix}:{revision.id}:{command.coverage_start}",
                input_hash=fingerprint(
                    {
                        "revision": str(revision.id),
                        "hash": revision.content_hash,
                        "week": str(command.coverage_start),
                    }
                ),
                created_at=stamp,
                started_at=stamp,
                finished_at=stamp + timedelta(seconds=1),
                error_json=None if index == 0 else {"type": "SyntheticRecordedFailure"},
                created_by="synthetic_history_seed",
                correlation_id=identifier,
                schema_version="1.0",
                metadata_json={},
            )
            session.add(task)
            await session.flush()
            if index == 0:
                session.add(
                    WeeklyResultRecord(
                        id=uuid4(),
                        task_run_id=identifier,
                        revision_id=revision.id,
                        week_start=command.coverage_start,
                        as_of=stamp,
                        status="SKIPPED_CLOSED",
                        reason_code="MARKET_CLOSED",
                        funnel_run_id=None,
                        funnel_event_id=None,
                        candidate_count=None,
                        created_by="synthetic_history_seed",
                        correlation_id=identifier,
                        schema_version=protocol,
                        metadata_json={},
                    )
                )
            seeded.append(identifier)
            if not include_legacy_other:
                continue
            other = uuid4()
            session.add(
                TaskRunRecord(
                    id=other,
                    task_name=f"{other_prefix}:{config.schedule_id}",
                    scheduled_for=stamp,
                    status="FAILED",
                    attempt=1,
                    idempotency_key=f"legacy-{other}",
                    input_hash="0" * 64,
                    created_at=stamp,
                    started_at=stamp,
                    finished_at=stamp,
                    error_json={"type": "SyntheticLegacyFailure"},
                    created_by="synthetic_history_seed",
                    correlation_id=other,
                    schema_version="1.0",
                    metadata_json={},
                )
            )
    return seeded


async def database_hashes(sessions):
    async with sessions() as session:
        names = await session.scalars(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        )
        return {
            name: await session.scalar(
                text(
                    "SELECT md5(coalesce(string_agg(row_to_json(t)::text, '' "
                    f"ORDER BY row_to_json(t)::text),'')) FROM \"{name}\" t"
                )
            )
            for name in names
        }


@pytest.mark.parametrize("protocol", ["1.0", "2.0"])
@pytest.mark.parametrize("count", [49, 50, 52])
async def test_authenticated_stable_weekly_pages_exact_original_revision_and_zero_get_effects(
    database_engine, monkeypatch, protocol, count
):
    sessions, store, config, seeded = await seed_history(
        database_engine, monkeypatch, protocol, count
    )
    reader = SqlWeeklyTaskHistory(sessions, protocol)
    before = await database_hashes(sessions)
    app = create_app(
        weekly_funnel_service=WeeklyService(store) if protocol == "1.0" else None,
        complete_weekly_service=CompleteWeeklyService(store) if protocol == "2.0" else None,
        write_api_token=TOKEN,
    )
    base = (
        "/api/v1/opportunities/" + ("weekly" if protocol == "1.0" else "complete-weekly") + "/tasks"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as client:
        assert (
            await client.get(base, headers={"Authorization": "Bearer invalid"})
        ).status_code == 401
        page = (await client.get(base)).json()
        assert len(page["items"]) == 50
        all_ids = [UUID(row["task_run_id"]) for row in page["items"]]
        cursor = page["next_cursor"]
        assert bool(cursor) == (count >= 50)
        while cursor:
            response = await client.get(base, params={"cursor": cursor})
            assert response.status_code == 200
            data = response.json()
            all_ids.extend(UUID(row["task_run_id"]) for row in data["items"])
            cursor = data["next_cursor"]
        assert len(all_ids) == count + 1 and len(set(all_ids)) == count + 1
        # Seeded creation timestamps tie. UUID ordering remains stable across pages.
        assert all_ids[1:] == sorted(seeded, reverse=True)
        original = seeded[0]
        statements = []

        def record_statement(_connection, _cursor, statement, _parameters, _context, _many):
            if "FROM task_run" in statement:
                statements.append(statement)

        event.listen(database_engine.sync_engine, "before_cursor_execute", record_statement)
        try:
            detail = (await client.get(f"{base}/{original}")).json()
        finally:
            event.remove(database_engine.sync_engine, "before_cursor_execute", record_statement)
        assert len(statements) == 1 and "LEFT OUTER JOIN weekly_funnel_result" in statements[0]
        assert detail["provenance"]["name"] == "SEEDED_OLD_REVISION_0"
        assert detail["revision_id"] != str(config.revision_id)
        assert detail["result_status"] == "SKIPPED_CLOSED"
        assert detail["funnel_run_id"] is None and detail["funnel_hash"] is None
        failed = (await client.get(f"{base}/{seeded[-1]}")).json()
        assert (
            failed["task_status"] == "FAILED"
            and failed["reason_code"] == "SyntheticRecordedFailure"
        )
        assert failed["attempt_history"] == "NOT_PROVIDED_CURRENT_RECORDED_ATTEMPT_ONLY"
        assert (await client.get(f"{base}/malformed")).status_code == 422
        assert (await client.get(f"{base}/{uuid4()}")).status_code == 404
        assert (await client.get(base, params={"cursor": "invalid"})).status_code == 422
        other = SqlWeeklyTaskHistory(sessions, "2.0" if protocol == "1.0" else "1.0")
        with pytest.raises(OpportunityError, match="WRONG_PROTOCOL"):
            await other.task(original)
        if page["next_cursor"]:
            with pytest.raises(OpportunityError, match="CURSOR_INVALID"):
                await other.tasks(page["next_cursor"])
        real = (await reader.tasks()).items[0]
        real_detail = await reader.task(real.task_run_id)
        assert real_detail.funnel_run_id is not None
        assert real_detail.funnel_hash is not None
    assert await database_hashes(sessions) == before


async def test_missing_revision_and_legacy_identity_are_explicit_read_only_unknowns(
    database_engine, monkeypatch
):
    sessions, _, _, _ = await seed_history(database_engine, monkeypatch, count=1)
    reader = SqlWeeklyTaskHistory(sessions, "2.0")
    legacy = (await reader.tasks()).items[0]
    detail = await reader.task(legacy.task_run_id)
    assert detail.revision_id is None and detail.provenance is None and detail.funnel_run_id is None
    assert "LEGACY_TASK_IDENTITY_NOT_PROVIDED" in detail.unknowns


@pytest.mark.parametrize("token", [None, "", "synthetic-weekly-history-only"])
async def test_new_weekly_history_authentication_precedes_service_and_old_overview_remains_readable(
    token,
):
    # None means environment fallback in production. Explicit empty disables that
    # fallback so ambient CI credentials cannot turn the no-token fixture into401.
    app = create_app(write_api_token=token or "")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for namespace in ("weekly", "complete-weekly"):
            response = await client.get(f"/api/v1/opportunities/{namespace}/tasks")
            assert response.status_code == (401 if token else 503)
            assert response.headers["www-authenticate"] == "Bearer"
            assert (await client.head(f"/api/v1/opportunities/{namespace}/tasks")).status_code == (
                401 if token else 503
            )
            assert (
                await client.options(f"/api/v1/opportunities/{namespace}/tasks")
            ).status_code == 405
            if token:
                authenticated = {"Authorization": f"Bearer {token}"}
                assert (
                    await client.get(
                        f"/api/v1/opportunities/{namespace}/tasks", headers=authenticated
                    )
                ).status_code == 503
                assert (
                    await client.head(
                        f"/api/v1/opportunities/{namespace}/tasks", headers=authenticated
                    )
                ).status_code == 405
            assert (await client.get(f"/api/v1/opportunities/{namespace}")).status_code == 503


async def test_retry_start_time_change_does_not_move_unloaded_task_across_cursor(
    database_engine, monkeypatch
):
    sessions, _, _, seeded = await seed_history(database_engine, monkeypatch, count=52)
    reader = SqlWeeklyTaskHistory(sessions, "1.0")
    first = await reader.tasks()
    unseen = min(seeded)
    async with sessions() as session, session.begin():
        record = await session.get(TaskRunRecord, unseen)
        record.started_at = datetime.now(UTC) + timedelta(days=1)
        record.attempt = 3
    next_page = await reader.tasks(first.next_cursor)
    assert unseen in {item.task_run_id for item in next_page.items}
    assert len({item.task_run_id for item in first.items + next_page.items}) == 53


async def test_unverified_original_input_hash_removes_provenance_and_artifact_link(
    database_engine, monkeypatch
):
    sessions, _, _, _ = await seed_history(database_engine, monkeypatch, count=1)
    reader = SqlWeeklyTaskHistory(sessions, "1.0")
    real = (await reader.tasks()).items[0]
    async with sessions() as session, session.begin():
        record = await session.get(TaskRunRecord, real.task_run_id)
        record.input_hash = "f" * 64
    detail = await reader.task(real.task_run_id)
    assert detail.provenance is None and detail.funnel_run_id is None
    assert "ORIGINAL_REVISION_MISSING_OR_UNVERIFIED" in detail.unknowns


@pytest.mark.parametrize("mismatch", ["revision", "week", "protocol"])
async def test_mismatched_result_is_unknown_without_artifact_substitution(
    database_engine, monkeypatch, mismatch
):
    sessions, _, config, seeded = await seed_history(database_engine, monkeypatch, count=2)
    async with sessions() as session, session.begin():
        task = await session.get(TaskRunRecord, seeded[-1])
        _, revision_id, week = task.idempotency_key.split(":")
        from datetime import date

        session.add(
            WeeklyResultRecord(
                id=uuid4(),
                task_run_id=task.id,
                revision_id=config.revision_id if mismatch == "revision" else UUID(revision_id),
                week_start=date.fromisoformat(week)
                + timedelta(days=7 if mismatch in {"week", "revision"} else 0),
                as_of=task.scheduled_for,
                status="SKIPPED_CLOSED",
                reason_code="MARKET_CLOSED",
                funnel_run_id=None,
                funnel_event_id=None,
                candidate_count=None,
                created_by="synthetic_mismatched_reference",
                correlation_id=task.id,
                schema_version="2.0" if mismatch == "protocol" else "1.0",
                metadata_json={},
            )
        )
    reader = SqlWeeklyTaskHistory(sessions, "1.0")
    before = await database_hashes(sessions)
    detail = await reader.task(seeded[-1])
    assert detail.result_status is None and detail.funnel_run_id is None
    assert "RESULT_REFERENCE_MISMATCH" in detail.unknowns
    assert await database_hashes(sessions) == before


@pytest.mark.parametrize("protocol", ["1.0", "2.0"])
async def test_legacy_artifact_raw_hash_survives_optional_default_expansion_on_audit_get(
    database_engine, monkeypatch, protocol
):
    import copy

    from sqlalchemy.orm import Session

    from investment_os.infrastructure.opportunities import digest
    from investment_os.infrastructure.persistence.models import EventLogRecord

    def legacy_before_flush(session, *_args):
        for record in session.new:
            if isinstance(record, EventLogRecord) and record.aggregate_type in {
                "opportunity_funnel_run",
                "opportunity_complete_scope_v2",
            }:
                payload = copy.deepcopy(record.payload_json)
                for row in payload["run"]["rows"]:
                    row.pop("lifecycle_snapshot", None)
                payload["snapshot_hash"] = digest(payload["run"])
                record.payload_json = payload

    event.listen(Session, "before_flush", legacy_before_flush)
    try:
        sessions, store, _, _ = await seed_history(database_engine, monkeypatch, protocol, count=1)
    finally:
        event.remove(Session, "before_flush", legacy_before_flush)
    reader = SqlWeeklyTaskHistory(sessions, protocol)
    real = (await reader.tasks()).items[0]
    async with sessions() as session:
        result = await session.scalar(
            select(WeeklyResultRecord).where(WeeklyResultRecord.task_run_id == real.task_run_id)
        )
        original = await session.get(EventLogRecord, result.funnel_event_id)
        raw = copy.deepcopy(original.payload_json)
        original_hash = raw["snapshot_hash"]
        assert original_hash == digest(raw["run"])
        assert all("lifecycle_snapshot" not in row for row in raw["run"]["rows"])
    app = create_app(
        weekly_funnel_service=WeeklyService(store) if protocol == "1.0" else None,
        complete_weekly_service=CompleteWeeklyService(store) if protocol == "2.0" else None,
        write_api_token=TOKEN,
    )
    namespace = "weekly" if protocol == "1.0" else "complete-weekly"
    before = await database_hashes(sessions)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/api/v1/opportunities/{namespace}/tasks/{real.task_run_id}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert response.status_code == 200
        assert response.json()["funnel_hash"] == original_hash
        assert response.json()["funnel_run_id"] == str(result.funnel_run_id)
    assert await database_hashes(sessions) == before
    async with sessions() as session:
        replayed = await session.get(EventLogRecord, result.funnel_event_id)
        assert replayed.payload_json == raw
