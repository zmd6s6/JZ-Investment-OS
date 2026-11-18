"""Real PG/API Calendar task audit, original sources, stable pages and zero writes."""

import base64
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, select, text
from test_calendar_product_persistence import command, enable, setup

from investment_os.api.calendar_routes import create_calendar_router
from investment_os.api.write_auth import WriteApiAuthMiddleware
from investment_os.application.calendar_product import CalendarProductError
from investment_os.infrastructure.calendar_product import (
    REPORT_EVENT,
    PersistedCalendarStatusRunner,
    _hash,
)
from investment_os.infrastructure.persistence.calendar_models import MarketSessionRecord
from investment_os.infrastructure.persistence.models import EventLogRecord, TaskRunRecord

pytestmark = pytest.mark.integration
TOKEN = "synthetic-calendar-history-only"


async def seed(sessions, config, count=102):
    stamp = datetime(2025, 1, 1, tzinfo=UTC)
    ids = []
    async with sessions() as session, session.begin():
        days = tuple(
            await session.scalars(
                select(MarketSessionRecord)
                .where(MarketSessionRecord.import_id == config.import_id)
                .order_by(MarketSessionRecord.business_date)
            )
        )
        for index, day in enumerate(days[:count]):
            identifier = UUID(int=index + 1)
            session.add(
                TaskRunRecord(
                    id=identifier,
                    task_name="calendar_status_SSE",
                    scheduled_for=day.close_at_utc,
                    status="FAILED",
                    attempt=3,
                    idempotency_key=f"calendar-status:SSE:{day.business_date}:{config.import_id}",
                    input_hash=_hash(
                        {
                            "venue": "SSE",
                            "business_date": day.business_date,
                            "close_at": day.close_at_utc,
                            "calendar_hash": config.content_hash,
                        }
                    ),
                    created_at=stamp,
                    started_at=stamp,
                    finished_at=stamp,
                    error_json={"type": "SyntheticRecordedFailure"},
                    created_by="synthetic_history_seed",
                    correlation_id=uuid4(),
                    schema_version="1.0",
                    metadata_json={},
                )
            )
            ids.append(identifier)
        # SQL LIKE underscore wildcards must not admit these false namespaces.
        for index in range(105):
            session.add(
                TaskRunRecord(
                    id=uuid4(),
                    task_name="calendarXstatusXSSE",
                    scheduled_for=stamp,
                    status="FAILED",
                    attempt=1,
                    idempotency_key=f"other-{index}",
                    input_hash="0" * 64,
                    started_at=stamp,
                    finished_at=stamp,
                    created_by="synthetic_history_seed",
                    correlation_id=uuid4(),
                    schema_version="1.0",
                    metadata_json={},
                )
            )
    return ids


async def history_setup(engine, count=102):
    sessions, service = setup(engine)
    days = "\n".join(f"{date(2025, 1, 1) + timedelta(days=i)},15:00" for i in range(count + 1))
    config = await service.import_calendar(command(days=days, source="SOURCE_A"))
    ids = await seed(sessions, config, count)
    return sessions, service, config, ids


@pytest.mark.parametrize("count", [30, 31, 50, 51, 102])
async def test_calendar_fixed50_pages_ties_exact_outside30_and_retry_boundary(
    database_engine, count
):
    sessions, service, _config, ids = await history_setup(database_engine, count)
    assert len((await service.overview()).recent_runs) == min(30, count)
    first = await service.tasks()
    assert first.page_size == 50 and len(first.items) == min(count, 50)
    assert [r.task_run_id for r in first.items] == list(reversed(ids))[:50]
    # A retry may move started_at but never changes the keyset boundary.
    async with sessions() as session, session.begin():
        row = await session.get(TaskRunRecord, ids[0])
        row.started_at = datetime.now(UTC)
    collected = [r.task_run_id for r in first.items]
    cursor = first.next_cursor
    while cursor:
        page = await service.tasks(cursor)
        assert len(page.items) <= 50
        collected.extend(r.task_run_id for r in page.items)
        cursor = page.next_cursor
    assert collected == list(reversed(ids)) and len(set(collected)) == count
    old = await service.task(ids[0])
    assert old.source.source_version == "SOURCE_A"
    assert (
        old.report_json is None
        and old.task_status == "FAILED"
        and old.reason_code == "SyntheticRecordedFailure"
    )
    assert "NO_COMMITTED_STATUS_REPORT" in old.unknowns


async def test_calendar_source_a_failure_survives_b_success_and_original_json_hash(database_engine):
    sessions, service, config, ids = await history_setup(database_engine, 31)
    active = await enable(service, config)
    produced = await PersistedCalendarStatusRunner(sessions).dispatch_due(
        now=datetime(2026, 11, 18, tzinfo=UTC)
    )
    assert len(produced) == 1
    before = await service.task(produced[0])
    assert before.source.source_version == "SOURCE_A"
    assert (
        before.report_event_id
        and before.report_json
        and before.report_hash == _hash(before.report_json)
    )
    corrected = await service.import_calendar(
        command(version=active.version, days="2025-01-01,15:00", source="SOURCE_B")
    )
    await enable(service, corrected)
    await PersistedCalendarStatusRunner(sessions).dispatch_due(
        now=datetime(2026, 11, 18, tzinfo=UTC)
    )
    old = await service.task(ids[0])
    assert old.source.source_version == "SOURCE_A" and old.report_json is None
    assert (await service.task(produced[0])) == before
    assert (await service.overview()).configurations[0].source_version == "SOURCE_B"


@pytest.mark.parametrize(
    "fault",
    [
        "key",
        "legacy",
        "namespace",
        "import",
        "session",
        "input",
        "missing_event",
        "mismatch_event",
        "unknown_status",
    ],
)
async def test_calendar_missing_or_mismatched_references_never_substitute_source(
    database_engine, fault
):
    sessions, service, config, ids = await history_setup(database_engine, 1)
    async with sessions() as session, session.begin():
        task = await session.get(TaskRunRecord, ids[0])
        if fault == "key":
            task.idempotency_key = "bad"
        elif fault == "legacy":
            task.idempotency_key = "calendar-status:SSE:2025-01-01"
        elif fault == "namespace":
            task.task_name = "calendarXstatusXSSE"
        elif fault == "import":
            task.idempotency_key = f"calendar-status:SSE:2025-01-01:{uuid4()}"
        elif fault == "session":
            task.idempotency_key = f"calendar-status:SSE:2024-01-01:{config.import_id}"
        elif fault == "input":
            task.input_hash = "0" * 64
        elif fault == "unknown_status":
            task.status = "PENDING"
        else:
            task.status = "SUCCEEDED"
            if fault == "mismatch_event":
                session.add(
                    EventLogRecord(
                        event_type=REPORT_EVENT,
                        aggregate_type="calendar_product",
                        aggregate_id=task.id,
                        payload_json={"source_name": "WRONG"},
                        occurred_at=datetime.now(UTC),
                        created_by="synthetic_history_seed",
                        correlation_id=uuid4(),
                        schema_version="1.0",
                        metadata_json={},
                    )
                )
    if fault == "namespace":
        with pytest.raises(CalendarProductError):
            await service.task(ids[0])
    else:
        detail = await service.task(ids[0])
        assert detail.report_json is None and detail.report_hash is None
        if fault in {"key", "legacy", "import", "session", "input"}:
            assert (
                detail.source is None and "ORIGINAL_SOURCE_MISSING_OR_UNVERIFIED" in detail.unknowns
            )
        if fault in {"missing_event", "mismatch_event"}:
            assert "REPORT_MISSING_OR_UNVERIFIED" in detail.unknowns
        if fault == "unknown_status":
            assert "UNSUPPORTED_RECORDED_STATUS" in detail.unknowns


@pytest.mark.parametrize(
    "cursor", ["", "bad", "a" * 1025, base64.urlsafe_b64encode(b'{"namespace":"other"}').decode()]
)
async def test_calendar_invalid_cursor_explicit_error(database_engine, cursor):
    _, service, _, _ = await history_setup(database_engine, 1)
    with pytest.raises(CalendarProductError, match="分页"):
        await service.tasks(cursor)


async def table_hashes(engine):
    async with engine.connect() as connection:
        names = tuple(
            await connection.scalars(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
            )
        )
        return {
            name: await connection.scalar(
                text(
                    "SELECT md5(COALESCE(string_agg(row_to_json(t)::text,'' "
                    "ORDER BY row_to_json(t)::text),'')) "
                    f'FROM "{name}" t'
                )
            )
            for name in names
        }


async def test_calendar_authenticated_get_head_options_sanitized503_and_zero_side_effects(
    database_engine,
):
    _sessions, service, _, ids = await history_setup(database_engine, 31)
    app = FastAPI()
    app.add_middleware(WriteApiAuthMiddleware, token=TOKEN)
    app.include_router(create_calendar_router(service))
    before = await table_hashes(database_engine)
    writes = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if (
            statement.lstrip()
            .upper()
            .startswith(("INSERT", "UPDATE", "DELETE", "TRUNCATE", "CREATE", "ALTER"))
        ):
            writes.append(statement)

    event.listen(database_engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            for path in ["/api/v1/calendar/tasks", f"/api/v1/calendar/tasks/{ids[0]}"]:
                assert (await client.get(path)).status_code == 401
                assert (await client.head(path)).status_code == 401
                assert (await client.options(path)).status_code == 405
                assert (
                    await client.head(path, headers={"Authorization": f"Bearer {TOKEN}"})
                ).status_code == 405
                result = await client.get(path, headers={"Authorization": f"Bearer {TOKEN}"})
                assert result.status_code == 200
            for suffix in ["bad", str(uuid4())]:
                response = await client.get(
                    "/api/v1/calendar/tasks/" + suffix, headers={"Authorization": f"Bearer {TOKEN}"}
                )
                assert response.status_code == 422
            assert (await client.get("/api/v1/calendar")).status_code == 200
        assert not writes
        assert await table_hashes(database_engine) == before
    finally:
        event.remove(database_engine.sync_engine, "before_cursor_execute", capture)
    missing = FastAPI()
    missing.add_middleware(WriteApiAuthMiddleware, token=None)
    missing.include_router(create_calendar_router(service))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=missing), base_url="http://test"
    ) as client:
        assert (await client.get("/api/v1/calendar/tasks")).status_code == 503
    down = FastAPI()
    down.add_middleware(WriteApiAuthMiddleware, token=TOKEN)
    down.include_router(create_calendar_router(None))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=down), base_url="http://test"
    ) as client:
        result = await client.get(
            "/api/v1/calendar/tasks", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        assert result.status_code == 503 and "password" not in result.text


@pytest.mark.parametrize(
    "field",
    [
        "venue",
        "business_date",
        "as_of",
        "calendar_import_id",
        "calendar_hash",
        "source_name",
        "source_version",
        "aggregate_type",
        "audit_hash",
    ],
)
async def test_calendar_valid_shaped_report_association_mismatch_is_unknown(database_engine, field):
    from investment_os.infrastructure.persistence.models import AuditLogRecord

    sessions, service, config, ids = await history_setup(database_engine, 1)
    correlation = uuid4()
    payload = {
        "report_kind": "CALENDAR_STATUS_ONLY",
        "venue": "SSE",
        "business_date": "2025-01-01",
        "as_of": "2025-01-01T07:00:00+00:00",
        "calendar_import_id": str(config.import_id),
        "calendar_hash": config.content_hash,
        "source_name": config.source_name,
        "source_version": config.source_version,
        "message": "SYNTHETIC_TEST_ORIGINAL_REPORT",
        "auto_trade": False,
        "paid_calls": 0,
    }
    changes = {
        "venue": "SZSE",
        "business_date": "2025-01-02",
        "as_of": "2025-01-02T07:00:00+00:00",
        "calendar_import_id": str(uuid4()),
        "calendar_hash": "0" * 64,
        "source_name": "OTHER_SOURCE",
        "source_version": "OTHER_VERSION",
    }
    if field in changes:
        payload[field] = changes[field]
    async with sessions() as session, session.begin():
        task = await session.get(TaskRunRecord, ids[0])
        task.status = "SUCCEEDED"
        session.add(
            EventLogRecord(
                event_type=REPORT_EVENT,
                aggregate_type="wrong" if field == "aggregate_type" else "calendar_product",
                aggregate_id=task.id,
                payload_json=payload,
                occurred_at=datetime.now(UTC),
                created_by="synthetic_history_seed",
                correlation_id=correlation,
                schema_version="1.0",
                metadata_json={},
            )
        )
        session.add(
            AuditLogRecord(
                actor_type="SYSTEM",
                actor_id="synthetic_history_seed",
                operation=REPORT_EVENT,
                entity_type="calendar_product",
                entity_id=task.id,
                before_hash=None,
                after_hash="0" * 64 if field == "audit_hash" else _hash(payload),
                ip_or_runtime_ref="synthetic-test",
                occurred_at=datetime.now(UTC),
                correlation_id=correlation,
                schema_version="1.0",
                created_by="synthetic_history_seed",
                metadata_json={},
            )
        )
    detail = await service.task(ids[0])
    assert detail.source is not None
    assert (
        detail.report_json is None and detail.report_event_id is None and detail.report_hash is None
    )
    assert "REPORT_MISSING_OR_UNVERIFIED" in detail.unknowns
