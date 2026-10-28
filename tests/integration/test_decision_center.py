"""Real PostgreSQL human review, cumulative fills, immutable audit and failure gates."""

import asyncio
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from decision_center_fixture import seed_center
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from investment_os.api.decision_center import decision_center_router
from investment_os.api.write_auth import WriteApiAuthMiddleware
from investment_os.application.decision_center import HumanCommand, ManualExecutionCommand
from investment_os.domain.approval import DecisionApproval
from investment_os.domain.enums import ApprovalAction, ExecutionMode, ExecutionStatus
from investment_os.domain.execution import DecisionExecution
from investment_os.domain.values import Quantity, UtcTimestamp
from investment_os.infrastructure.decision_center import SqlDecisionCenter
from investment_os.infrastructure.decision_journal import SqlAlchemyDecisionJournalWriter

pytestmark = pytest.mark.integration


async def test_decision_list_batches_queries_instead_of_loading_every_lineage(database_engine):
    await seed_center(database_engine, decision_count=12)
    center = SqlDecisionCenter(async_sessionmaker(database_engine, expire_on_commit=False))
    queries = []

    def query_seen(_connection, _cursor, statement, _parameters, _context, _executemany):
        queries.append(statement)

    event.listen(database_engine.sync_engine, "before_cursor_execute", query_seen)
    try:
        cards = await center.list()
    finally:
        event.remove(database_engine.sync_engine, "before_cursor_execute", query_seen)
    assert len(cards) == 12 and len(queries) <= 6
    assert all(card.blockers == ("DETAIL_REVIEW_REQUIRED",) for card in cards)


async def test_nonempty_human_history_refuses_downgrade_and_preserves_receipt(database_engine):
    ids = await seed_center(database_engine)
    center = SqlDecisionCenter(async_sessionmaker(database_engine, expire_on_commit=False))
    await center.act(ids["decision"], "APPROVE", human())
    with pytest.raises(DBAPIError, match="human Decision history exists"):
        await asyncio.to_thread(alembic_command.downgrade, Config("alembic.ini"), "20261028_0016")
    assert len((await center.get(ids["decision"])).history) == 1


async def test_false_veto_without_evaluated_flags_remains_unknown_and_cannot_approve(
    database_engine,
):
    ids = await seed_center(database_engine, risk_unknown=True)
    center = SqlDecisionCenter(async_sessionmaker(database_engine, expire_on_commit=False))
    view = await center.get(ids["decision"])
    assert "RISK_UNKNOWN" in view.decision.blockers and "APPROVE" not in view.allowed_actions
    with pytest.raises(ValueError):
        await center.act(ids["decision"], "APPROVE", human())


async def test_sizing_action_must_match_the_decision_before_human_approval(database_engine):
    ids = await seed_center(database_engine, sizing_action_mismatch=True)
    center = SqlDecisionCenter(async_sessionmaker(database_engine, expire_on_commit=False))
    assert "SIZING_INPUT_INVALID" in (await center.get(ids["decision"])).decision.blockers
    with pytest.raises(ValueError):
        await center.act(ids["decision"], "APPROVE", human())


def human(revision=1, **changes):
    return HumanCommand(
        request_id=uuid4(),
        expected_revision=revision,
        actor_id="synthetic-human",
        comment="明确人工审阅合成输入",
        confirmed=True,
        **changes,
    )


async def test_legacy_human_records_are_visible_read_only_without_fabricated_fees_or_time(
    database_engine,
):
    ids = await seed_center(database_engine)
    sessions = async_sessionmaker(database_engine, expire_on_commit=False)
    approval = DecisionApproval(
        decision_id=ids["decision"],
        actor_id="synthetic-old-human",
        action=ApprovalAction.APPROVE,
        occurred_at=UtcTimestamp(ids["now"]),
        expires_at=UtcTimestamp(ids["now"] + timedelta(hours=1)),
        comment="原始人工理由",
    )
    writer = SqlAlchemyDecisionJournalWriter(sessions)
    await writer.append_approval(approval)
    execution = DecisionExecution(
        decision_id=ids["decision"],
        approval=approval,
        mode=ExecutionMode.MANUAL,
        status=ExecutionStatus.FILLED,
        requested_quantity=Quantity(1),
        filled_quantity=Quantity(1),
        recorded_at=UtcTimestamp(ids["now"]),
        average_price="10",
        external_references=("synthetic-old-reference",),
    )
    await writer.append_execution(execution)
    center = SqlDecisionCenter(sessions)
    view = await center.get(ids["decision"])
    assert view.decision.state == "LEGACY_REVIEW_REQUIRED" and view.allowed_actions == ()
    assert len(view.history) == 2 and all(item["legacy"] for item in view.history)
    old_fill = next(item["execution"] for item in view.history if "execution" in item)
    assert old_fill["fees"] is None and old_fill["executed_at"] is None and old_fill["note"] is None
    assert old_fill["references"] == ["synthetic-old-reference"]
    with pytest.raises(ValueError):
        await center.act(ids["decision"], "APPROVE", human())


async def test_same_timestamp_revoke_uses_action_revision_not_random_uuid_order(database_engine):
    ids = await seed_center(database_engine)
    center = SqlDecisionCenter(
        async_sessionmaker(database_engine, expire_on_commit=False),
        now=lambda: ids["now"] + timedelta(seconds=1),
    )
    await center.act(ids["decision"], "APPROVE", human())
    view = await center.act(ids["decision"], "REVOKE", human(2))
    assert view.decision.state == "CANCELLED" and view.approval_id is None
    assert view.allowed_actions == ()
    assert [item["action"] for item in view.history] == ["APPROVE", "REVOKE"]


async def test_real_center_approval_partial_fills_complete_fees_and_immutable_history(
    database_engine,
):
    ids = await seed_center(database_engine)
    now = ids["now"] + timedelta(seconds=1)
    sessions = async_sessionmaker(database_engine, expire_on_commit=False)
    center = SqlDecisionCenter(sessions, now=lambda: now)
    before = await center.get(ids["decision"])
    assert before.decision.blockers == () and before.allowed_actions == ("REJECT", "APPROVE")
    command = human()
    approved = await center.act(ids["decision"], "APPROVE", command)
    assert approved.decision.state == "APPROVED" and approved.decision.revision == 2
    assert (await center.act(ids["decision"], "APPROVE", command)).decision.revision == 2
    for index, quantity in enumerate((Decimal(20), ids["quantity"] - 20)):
        now += timedelta(seconds=1)
        fill = ManualExecutionCommand(
            request_id=uuid4(),
            expected_revision=2 + index,
            actor_id="synthetic-human",
            comment="合成外部成交事实",
            confirmed=True,
            approval_id=approved.approval_id,
            quantity=quantity,
            price="10",
            fees="1.25",
            executed_at=now,
            external_reference="  synthetic-301\nreference ",
            note=" 外部已成交\x00记录 ",
        )
        view = await center.act(ids["decision"], "RECORD_EXECUTION", fill)
        assert view.history[-1]["execution"]["fees"] == "1.250000000000000000"
        assert view.history[-1]["execution"]["note"] == "外部已成交记录"
    assert view.decision.state == "EXECUTED" and view.remaining_quantity == 0
    assert view.filled_quantity == ids["quantity"] and view.allowed_actions == ()
    async with database_engine.connect() as connection:
        assert (
            await connection.scalar(
                text("SELECT state FROM investment_decision WHERE id=:id"), {"id": ids["decision"]}
            )
            == "PENDING_APPROVAL"
        )
        assert await connection.scalar(text("SELECT count(*) FROM decision_center_action")) == 3
        assert (
            await connection.scalar(
                text("SELECT count(*) FROM outbox_event WHERE topic='decision.human-action'")
            )
            == 3
        )
    for table in (
        "decision_center_action",
        "manual_execution_detail",
        "decision_approval",
        "decision_execution",
    ):
        async with database_engine.begin() as connection:
            with pytest.raises(DBAPIError):
                await connection.execute(text(f"DELETE FROM {table}"))


@pytest.mark.parametrize("action", ["REJECT", "REVOKE"])
async def test_explicit_reject_and_revoke_stop_execution(database_engine, action):
    ids = await seed_center(database_engine)
    now = ids["now"] + timedelta(seconds=1)
    center = SqlDecisionCenter(
        async_sessionmaker(database_engine, expire_on_commit=False), now=lambda: now
    )
    revision = 1
    if action == "REVOKE":
        await center.act(ids["decision"], "APPROVE", human())
        revision = 2
        now += timedelta(seconds=1)
    view = await center.act(ids["decision"], action, human(revision))
    assert view.decision.state == ("CANCELLED" if action == "REVOKE" else "REJECTED")
    assert view.approval_id is None and "RECORD_EXECUTION" not in view.allowed_actions
    with pytest.raises(ValueError):
        await center.act(ids["decision"], "APPROVE", human(view.decision.revision))


@pytest.mark.parametrize(
    "veto,policy_active,reason", [(True, True, "RISK_VETO"), (False, False, "POLICY_NOT_APPROVED")]
)
async def test_veto_and_test_default_never_approve(database_engine, veto, policy_active, reason):
    ids = await seed_center(database_engine, veto=veto, policy_active=policy_active)
    center = SqlDecisionCenter(async_sessionmaker(database_engine, expire_on_commit=False))
    view = await center.get(ids["decision"])
    assert reason in view.decision.blockers and "APPROVE" not in view.allowed_actions
    with pytest.raises(ValueError):
        await center.act(ids["decision"], "APPROVE", human())


async def test_concurrent_revision_and_idempotency_conflicts_never_duplicate(database_engine):
    ids = await seed_center(database_engine)
    center = SqlDecisionCenter(async_sessionmaker(database_engine, expire_on_commit=False))
    outcomes = await asyncio.gather(
        center.act(ids["decision"], "APPROVE", human()),
        center.act(ids["decision"], "REJECT", human()),
        return_exceptions=True,
    )
    assert sum(isinstance(o, ValueError) for o in outcomes) == 1
    assert (await center.get(ids["decision"])).decision.revision == 2
    async with database_engine.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM decision_approval")) == 1


async def test_expiry_exact_boundary_and_portfolio_drift_fail_closed(database_engine):
    ids = await seed_center(database_engine)
    now = ids["now"] + timedelta(seconds=1)
    center = SqlDecisionCenter(
        async_sessionmaker(database_engine, expire_on_commit=False), now=lambda: now
    )
    approved = await center.act(ids["decision"], "APPROVE", human())
    now = approved.approval_expires_at
    assert (await center.get(ids["decision"])).decision.state == "EXPIRED"
    now = ids["now"] + timedelta(seconds=3)
    async with database_engine.begin() as connection:
        await connection.execute(
            text("UPDATE portfolio SET cash_balance=cash_balance+1 WHERE id=:id"),
            {"id": ids["portfolio"]},
        )
    assert "PORTFOLIO_INPUT_CHANGED" in (await center.get(ids["decision"])).decision.blockers
    assert "RECORD_EXECUTION" not in (await center.get(ids["decision"])).allowed_actions


@pytest.mark.parametrize(
    "field,value",
    [
        ("quantity", "999999"),
        ("price", "10.01"),
        ("executed_at", "2000-01-01T00:00:00Z"),
        ("approval_id", None),
    ],
)
async def test_manual_wrong_quantity_price_time_or_approval_rejected(database_engine, field, value):
    ids = await seed_center(database_engine)
    center = SqlDecisionCenter(async_sessionmaker(database_engine, expire_on_commit=False))
    approved = await center.act(ids["decision"], "APPROVE", human())
    values = {
        "request_id": uuid4(),
        "expected_revision": 2,
        "actor_id": "synthetic-human",
        "comment": "合成成交",
        "confirmed": True,
        "approval_id": approved.approval_id,
        "quantity": "1",
        "price": "10",
        "fees": "0",
        "executed_at": approved.as_of,
        "external_reference": "synthetic",
        "note": "synthetic",
    }
    values[field] = uuid4() if field == "approval_id" else value
    with pytest.raises(ValueError):
        await center.act(ids["decision"], "RECORD_EXECUTION", ManualExecutionCommand(**values))
    assert len((await center.get(ids["decision"])).history) == 1


async def test_actual_router_auth_invalid_shadow_and_empty_list(database_engine):
    center = SqlDecisionCenter(async_sessionmaker(database_engine, expire_on_commit=False))
    app = FastAPI()
    app.add_middleware(WriteApiAuthMiddleware, token="synthetic-301-only")
    app.include_router(decision_center_router(center))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/decision-center")).json() == []
        path = f"/api/v1/decision-center/{uuid4()}/approve"
        payload = human().model_dump(mode="json")
        assert (await client.post(path, json=payload)).status_code == 401
        assert (
            await client.post(
                path, json=payload, headers={"Authorization": "Bearer synthetic-301-only"}
            )
        ).status_code == 404
        ids = await seed_center(database_engine)
        response = await client.get(f"/api/v1/decision-center/{ids['decision']}")
        assert response.status_code == 200 and response.json()["auto_trade"] is False
        command = human().model_dump(mode="json")
        response = await client.post(
            f"/api/v1/decision-center/{ids['decision']}/approve",
            json=command,
            headers={"Authorization": "Bearer synthetic-301-only"},
        )
        assert response.status_code == 200
        command["comment"] = "different reuse"
        assert (
            await client.post(
                f"/api/v1/decision-center/{ids['decision']}/approve",
                json=command,
                headers={"Authorization": "Bearer synthetic-301-only"},
            )
        ).status_code == 409


@pytest.mark.parametrize("gate", ["risk", "evidence", "review"])
@pytest.mark.parametrize("offset_us", [-1, 0, 1])
async def test_action_time_rechecks_expiry_after_suspended_detail_without_partial_facts(
    database_engine, gate, offset_us
):
    lifetime = timedelta(hours=1)
    ids = await seed_center(database_engine, **{f"{gate}_lifetime": lifetime})
    clock = [ids["now"] + timedelta(seconds=1)]
    entered, release = asyncio.Event(), asyncio.Event()

    class PausedCenter(SqlDecisionCenter):
        async def _detail(self, session, decision):
            result = await super()._detail(session, decision)
            if not entered.is_set():
                assert "APPROVE" in result.allowed_actions, result.decision.blockers
                entered.set()
                await release.wait()
            return result

    center = PausedCenter(
        async_sessionmaker(database_engine, expire_on_commit=False), now=lambda: clock[0]
    )
    command = human()
    task = asyncio.create_task(center.act(ids["decision"], "APPROVE", command))
    await asyncio.wait_for(entered.wait(), timeout=10)
    clock[0] = ids["now"] + lifetime + timedelta(microseconds=offset_us)
    release.set()
    if offset_us < 0:
        view = await task
        assert view.decision.state == "APPROVED"
        assert view.history[-1]["occurred_at"] == clock[0].isoformat()
    else:
        with pytest.raises(ValueError, match="DECISION_ACTION_BLOCKED"):
            await task
        async with database_engine.connect() as connection:
            for table in (
                "decision_approval",
                "decision_center_action",
                "audit_log",
                "outbox_event",
            ):
                column = "id" if table == "decision_center_action" else "correlation_id"
                count = await connection.scalar(
                    text(f"SELECT count(*) FROM {table} WHERE {column}=:id"),
                    {"id": command.request_id},
                )
                assert count == 0, table


@pytest.mark.parametrize(
    "defect",
    [
        "empty_thesis",
        "missing_thesis_relation",
        "missing_risk_relation",
        "thesis_expired_reference",
        "risk_expired_reference",
        "sizing_shell",
        "sizing_forged_output",
        "sizing_tampered_nav",
        "agent_risk_unlinked",
        "agent_thesis_impact_unlinked",
        "agent_expired_reference",
        "agent_future_reference",
    ],
)
async def test_complete_chain_rejects_unbacked_thesis_risk_or_sizing_without_writes(
    database_engine, defect
):
    ids = await seed_center(database_engine, chain_defect=defect)
    center = SqlDecisionCenter(async_sessionmaker(database_engine, expire_on_commit=False))
    view = await center.get(ids["decision"])
    assert view.decision.blockers and "APPROVE" not in view.allowed_actions
    command = human()
    with pytest.raises(ValueError, match="DECISION_ACTION_BLOCKED"):
        await center.act(ids["decision"], "APPROVE", command)
    async with database_engine.connect() as connection:
        for table in (
            "decision_approval",
            "decision_center_action",
            "audit_log",
            "outbox_event",
            "event_log",
        ):
            column = "id" if table == "decision_center_action" else "correlation_id"
            assert (
                await connection.scalar(
                    text(f"SELECT count(*) FROM {table} WHERE {column}=:id"),
                    {"id": command.request_id},
                )
                == 0
            )


async def test_concurrent_same_request_across_decisions_returns_one_success_one_conflict(
    database_engine,
):
    ids = await seed_center(database_engine, decision_count=2)
    center = SqlDecisionCenter(async_sessionmaker(database_engine, expire_on_commit=False))
    app = FastAPI()
    app.add_middleware(WriteApiAuthMiddleware, token="synthetic-301-only")
    app.include_router(decision_center_router(center))
    payload = human().model_dump(mode="json")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = await asyncio.gather(
            *(
                client.post(
                    f"/api/v1/decision-center/{identifier}/approve",
                    json=payload,
                    headers={"Authorization": "Bearer synthetic-301-only"},
                )
                for identifier in ids["decisions"]
            )
        )
    assert sorted(response.status_code for response in responses) == [200, 409]
    async with database_engine.connect() as connection:
        for table in (
            "decision_approval",
            "decision_center_action",
            "audit_log",
            "outbox_event",
            "event_log",
        ):
            column = "id" if table == "decision_center_action" else "correlation_id"
            assert (
                await connection.scalar(
                    text(f"SELECT count(*) FROM {table} WHERE {column}=:id"),
                    {"id": payload["request_id"]},
                )
                == 1
            )


@pytest.mark.parametrize("action", ["RECORD_EXECUTION", "REVOKE"])
@pytest.mark.parametrize("offset_us", [-1, 0, 1])
async def test_action_time_rechecks_approval_expiry_after_suspended_detail(
    database_engine, action, offset_us
):
    ids = await seed_center(
        database_engine,
        risk_lifetime=timedelta(days=7),
        evidence_lifetime=timedelta(days=7),
        review_lifetime=timedelta(days=7),
    )
    sessions = async_sessionmaker(database_engine, expire_on_commit=False)
    clock = [ids["now"] + timedelta(seconds=1)]
    approved = await SqlDecisionCenter(sessions, now=lambda: clock[0]).act(
        ids["decision"], "APPROVE", human()
    )
    entered, release = asyncio.Event(), asyncio.Event()

    class PausedCenter(SqlDecisionCenter):
        async def _detail(self, session, decision):
            result = await super()._detail(session, decision)
            if not entered.is_set():
                assert action in result.allowed_actions
                entered.set()
                await release.wait()
            return result

    center = PausedCenter(sessions, now=lambda: clock[0])
    command = (
        human(2)
        if action == "REVOKE"
        else ManualExecutionCommand(
            request_id=uuid4(),
            expected_revision=2,
            actor_id="synthetic-human",
            comment="合成成交事实",
            confirmed=True,
            approval_id=approved.approval_id,
            quantity="1",
            price="10",
            fees="0",
            executed_at=clock[0],
            external_reference="synthetic-approval-time",
            note="合成时点测试",
        )
    )
    task = asyncio.create_task(center.act(ids["decision"], action, command))
    await asyncio.wait_for(entered.wait(), timeout=10)
    clock[0] = approved.approval_expires_at + timedelta(microseconds=offset_us)
    release.set()
    if offset_us < 0:
        result = await task
        assert result.history[-1]["occurred_at"] == clock[0].isoformat()
    else:
        with pytest.raises(ValueError, match="DECISION_ACTION_BLOCKED"):
            await task
        async with database_engine.connect() as connection:
            for table in (
                "decision_approval",
                "decision_execution",
                "decision_center_action",
                "audit_log",
                "outbox_event",
            ):
                column = "id" if table == "decision_center_action" else "correlation_id"
                assert (
                    await connection.scalar(
                        text(f"SELECT count(*) FROM {table} WHERE {column}=:id"),
                        {"id": command.request_id},
                    )
                    == 0
                )


@pytest.mark.parametrize("gate", ["approved", "effective"])
@pytest.mark.parametrize("offset_us", [-1, 0, 1])
async def test_action_time_rechecks_policy_start_after_clock_change(
    database_engine, gate, offset_us
):
    ids = await seed_center(database_engine, **{f"policy_{gate}_delta": timedelta(hours=1)})
    clock = [ids["now"] + timedelta(hours=2)]
    entered, release = asyncio.Event(), asyncio.Event()

    class PausedCenter(SqlDecisionCenter):
        async def _detail(self, session, decision):
            result = await super()._detail(session, decision)
            if not entered.is_set():
                assert "APPROVE" in result.allowed_actions
                entered.set()
                await release.wait()
            return result

    center = PausedCenter(
        async_sessionmaker(database_engine, expire_on_commit=False), now=lambda: clock[0]
    )
    command = human()
    task = asyncio.create_task(center.act(ids["decision"], "APPROVE", command))
    await asyncio.wait_for(entered.wait(), timeout=10)
    clock[0] = ids["now"] + timedelta(hours=1, microseconds=offset_us)
    release.set()
    if offset_us >= 0:
        result = await task
        assert result.history[-1]["occurred_at"] == clock[0].isoformat()
    else:
        with pytest.raises(ValueError, match="DECISION_ACTION_BLOCKED"):
            await task
        async with database_engine.connect() as connection:
            for table in (
                "decision_approval",
                "decision_center_action",
                "audit_log",
                "outbox_event",
            ):
                column = "id" if table == "decision_center_action" else "correlation_id"
                assert (
                    await connection.scalar(
                        text(f"SELECT count(*) FROM {table} WHERE {column}=:id"),
                        {"id": command.request_id},
                    )
                    == 0
                )
