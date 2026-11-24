"""Real PostgreSQL stable historical navigation, compatibility and zero read effects."""

import base64
import json
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from test_analysis_runs_persistence import prepare

from investment_os.api.analysis_routes import analysis_router
from investment_os.application.analysis_runs import analysis_command_payload
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.infrastructure.analysis_runs import audit
from investment_os.infrastructure.persistence.analysis_models import AnalysisRunRecord

pytestmark = pytest.mark.integration


async def seed_history(engine, count):
    sessions, store, snapshot = await prepare(engine)
    async with sessions() as session, session.begin():
        for i in range(count):
            identifier = UUID(int=i + 1)
            command = snapshot.command.model_copy(update={"request_id": uuid4()})
            queued = snapshot.model_copy(update={"command": command})
            session.add(
                AnalysisRunRecord(
                    id=identifier,
                    request_id=command.request_id,
                    portfolio_id=snapshot.command.portfolio_id,
                    instrument_id=snapshot.command.instrument_id,
                    status="FAILED" if i % 2 else "CANCELLED",
                    queued_at=snapshot.queued_at,
                    started_at=snapshot.queued_at + timedelta(seconds=count - i),
                    finished_at=snapshot.queued_at + timedelta(minutes=1),
                    error_code="SYNTHETIC_SEEDED_HISTORY",
                    cancel_requested=False,
                    request_hash=fingerprint(analysis_command_payload(command)),
                    queued_input_json=queued.model_dump(mode="json"),
                    version=1,
                    **audit(identifier),
                )
            )
    return sessions, store, snapshot


async def database_snapshot(sessions):
    async with sessions() as session:
        names = (
            await session.scalars(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
            )
        ).all()
        return {
            name: (
                await session.scalars(
                    text(f'SELECT to_jsonb(t)::text FROM "{name}" t ORDER BY to_jsonb(t)::text')
                )
            ).all()
            for name in names
        }


@pytest.mark.parametrize("count", [30, 31, 101, 137])
async def test_history_tied_queued_at_uuid_pages_have_no_omissions_or_duplicates(
    database_engine, count
):
    sessions, store, snapshot = await seed_history(database_engine, count)
    before = await database_snapshot(sessions)
    seen, cursor = [], None
    while True:
        page = await store.history(portfolio_id=snapshot.command.portfolio_id, cursor=cursor)
        assert 0 < len(page.items) <= 30
        assert all(r.shadow_decision is None and r.frozen_input is None for r in page.items)
        seen.extend(r.run_id for r in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert seen == [UUID(int=i + 1) for i in range(count)]
    assert len(await store.list_runs()) == min(30, count)
    assert len(await store.list_runs(limit=999)) == min(100, count)
    old = await store.get(UUID(int=count))
    assert old.status in {"FAILED", "CANCELLED"} and old.shadow_decision is None
    assert old.request is not None
    assert await database_snapshot(sessions) == before


async def test_history_cursor_binds_portfolio_query_namespace_order_and_rejects_malformed(
    database_engine,
):
    _, store, snapshot = await seed_history(database_engine, 31)
    book, instrument = snapshot.command.portfolio_id, snapshot.command.instrument_id
    page = await store.history(portfolio_id=book)
    assert page.next_cursor
    for kwargs in [dict(portfolio_id=uuid4()), dict(portfolio_id=book, instrument_id=instrument)]:
        with pytest.raises(ValueError, match="ANALYSIS_HISTORY_CURSOR_INVALID"):
            await store.history(**kwargs, cursor=page.next_cursor)
    payload = json.loads(base64.urlsafe_b64decode(page.next_cursor))
    bad = ["", "!bad", "a" * 1025]
    for key, value in [
        ("namespace", "calendar_status"),
        ("ordering", "started_at_desc"),
        ("queued_at", "not-a-time"),
        ("run_id", "invalid"),
    ]:
        bad.append(base64.urlsafe_b64encode(json.dumps({**payload, key: value}).encode()).decode())
    for cursor in bad:
        with pytest.raises(ValueError, match="ANALYSIS_HISTORY_CURSOR_INVALID"):
            await store.history(portfolio_id=book, cursor=cursor)
    filtered = await store.history(portfolio_id=book, instrument_id=instrument)
    assert len(filtered.items) == 30
    assert (await store.history(portfolio_id=book, instrument_id=uuid4())).items == ()
    assert (await store.history(portfolio_id=uuid4())).items == ()


async def test_history_api_preserves_legacy_read_permissions_tuple_exact_and_zero_writes(
    database_engine,
):
    from fastapi import FastAPI

    from investment_os.api.write_auth import WriteApiAuthMiddleware

    sessions, store, snapshot = await seed_history(database_engine, 101)
    app = FastAPI()
    # Reads use the same availability check and middleware as existing Analysis GETs.
    app.include_router(analysis_router(object(), store, object()))
    app.add_middleware(WriteApiAuthMiddleware, token="synthetic-history-token")
    before = await database_snapshot(sessions)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        path = f"/api/v1/analysis/runs/history?portfolio_id={snapshot.command.portfolio_id}"
        for headers in [
            {},
            {"Authorization": "Bearer wrong"},
            {"Authorization": "Bearer synthetic-history-token"},
        ]:
            page = await client.get(path, headers=headers)
            assert page.status_code == 200 and len(page.json()["items"]) == 30
        legacy = await client.get(
            f"/api/v1/analysis/runs?portfolio_id={snapshot.command.portfolio_id}"
        )
        assert legacy.status_code == 200 and isinstance(legacy.json(), list)
        exact = await client.get(f"/api/v1/analysis/runs/{UUID(int=101)}")
        assert exact.status_code == 200 and exact.json()["error_code"] == "SYNTHETIC_SEEDED_HISTORY"
        assert (await client.get(path + "&cursor=bad")).status_code == 422
        assert (await client.get("/api/v1/analysis/runs/history")).status_code == 422
        assert (
            await client.get("/api/v1/analysis/runs/history?portfolio_id=bad")
        ).status_code == 422
        assert (await client.get(f"/api/v1/analysis/runs/{uuid4()}")).status_code == 404
        assert (await client.post(f"/api/v1/analysis/runs/{UUID(int=1)}/cancel")).status_code == 401
        assert (await client.request("HEAD", path)).status_code == 405
        assert (await client.options(path)).status_code == 405
    assert await database_snapshot(sessions) == before
