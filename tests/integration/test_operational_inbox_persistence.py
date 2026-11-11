"""Persisted Decision Center eligibility drives the read-only dashboard."""

from datetime import timedelta

import pytest
from decision_center_fixture import seed_center
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker

from investment_os.api.operational_inbox import operational_inbox_router
from investment_os.infrastructure.decision_center import SqlDecisionCenter

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("mode", ["valid", "veto", "policy", "expired", "unknown", "empty"])
async def test_inbox_reads_real_eligibility_without_writes(database_engine, mode):
    options = {
        "veto": mode == "veto",
        "policy_active": mode != "policy",
        "risk_unknown": mode == "unknown",
        "review_lifetime": timedelta(seconds=-1) if mode == "expired" else timedelta(days=1),
    }
    ids = await seed_center(database_engine, **options) if mode != "empty" else {}
    center = SqlDecisionCenter(async_sessionmaker(database_engine, expire_on_commit=False))
    app = FastAPI()
    app.include_router(operational_inbox_router(center, None, None))
    writes = []

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    event.listen(database_engine.sync_engine, "before_cursor_execute", record)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/operational-inbox")
            assert response.status_code == 200
            section = response.json()["pending_approvals"]
            assert section["state"] == ("AVAILABLE" if mode == "valid" else "EMPTY")
            if mode == "valid":
                assert section["items"][0]["source_id"] == str(ids["decision"])
                assert section["items"][0]["detail_url"].endswith(str(ids["decision"]))
            assert response.json()["auto_trade"] is False
            assert response.json()["risk_veto"]["state"] == "NOT_PROVIDED"
    finally:
        event.remove(database_engine.sync_engine, "before_cursor_execute", record)
    assert writes == []
