import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

EXPECTED_CORE_TABLES = {
    "investment_policy",
    "investment_policy_version",
    "strategy_version",
    "strategy_proposal",
    "portfolio",
    "portfolio_snapshot",
    "position",
    "position_lot",
    "trade_record",
    "instrument",
    "instrument_state",
    "instrument_state_transition",
    "evidence",
    "research_artifact",
    "feature_snapshot",
    "investment_thesis",
    "thesis_version",
    "agent_run",
    "agent_opinion",
    "agent_performance",
    "committee_session",
    "committee_message",
    "conflict_record",
    "risk_snapshot",
    "risk_assessment",
    "position_sizing_run",
    "investment_decision",
    "decision_approval",
    "decision_execution",
    "decision_outcome",
    "decision_review",
    "task_run",
    "event_log",
    "outbox_event",
    "audit_log",
}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_empty_database_downgrade_and_upgrade_create_all_core_tables(
    database_engine: AsyncEngine,
) -> None:
    await database_engine.dispose()
    config = Config("alembic.ini")
    await asyncio.to_thread(command.downgrade, config, "base")
    await asyncio.to_thread(command.upgrade, config, "head")

    async with database_engine.connect() as connection:
        table_names = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
        evidence_unique = await connection.run_sync(
            lambda sync: inspect(sync).get_unique_constraints("evidence")
        )
        task_unique = await connection.run_sync(
            lambda sync: inspect(sync).get_unique_constraints("task_run")
        )
        decision_columns = {
            str(column["name"])
            for column in await connection.run_sync(
                lambda sync: inspect(sync).get_columns("investment_decision")
            )
        }

    assert table_names >= EXPECTED_CORE_TABLES
    assert frozenset({"source_name", "source_locator", "content_hash"}) in {
        frozenset(item["column_names"]) for item in evidence_unique
    }
    assert frozenset({"idempotency_key"}) in {
        frozenset(item["column_names"]) for item in task_unique
    }
    assert {
        "position_before_json",
        "position_after_proposed_json",
        "unknowns_json",
        "dissent_json",
        "prompt_bundle_version",
        "formula_version",
        "content_hash",
    } <= decision_columns


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_and_event_history_are_database_enforced_append_only(
    database_engine: AsyncEngine,
) -> None:
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO audit_log "
                "(id, actor_type, actor_id, operation, entity_type, entity_id, "
                "ip_or_runtime_ref, occurred_at, created_by, correlation_id) "
                "VALUES (gen_random_uuid(), 'SYSTEM', 'test', 'CREATE', 'fixture', "
                "gen_random_uuid(), 'pytest', now(), 'pytest', gen_random_uuid())"
            )
        )

    with pytest.raises(DBAPIError):
        async with database_engine.begin() as connection:
            await connection.execute(text("UPDATE audit_log SET operation = 'ALTER'"))

    async with database_engine.connect() as connection:
        trigger_count = await connection.scalar(
            text(
                "SELECT count(*) FROM pg_trigger "
                "WHERE tgname IN ("
                "'trg_agent_run_append_only', 'trg_audit_log_append_only', "
                "'trg_committee_message_append_only', 'trg_committee_session_append_only', "
                "'trg_conflict_record_append_only', 'trg_event_log_append_only'"
                ")"
            )
        )
    assert trigger_count == 6


@pytest.mark.integration
@pytest.mark.asyncio
async def test_core_schema_uses_uuid_keys_numeric_financials_and_timezone_aware_time(
    database_engine: AsyncEngine,
) -> None:
    def inspect_schema(
        sync_connection: object,
    ) -> dict[str, tuple[dict[str, object], list[dict[str, object]]]]:
        inspector = inspect(sync_connection)
        return {
            table_name: (
                inspector.get_pk_constraint(table_name),
                inspector.get_columns(table_name),
            )
            for table_name in EXPECTED_CORE_TABLES
        }

    async with database_engine.connect() as connection:
        schema = await connection.run_sync(inspect_schema)

    for table_name, (primary_key, columns) in schema.items():
        assert primary_key["constrained_columns"] == ["id"], table_name
        id_column = next(column for column in columns if column["name"] == "id")
        assert str(id_column["type"]) == "UUID", table_name
        for column in columns:
            column_name = str(column["name"])
            if column_name.endswith("_at") or column_name in {
                "as_of",
                "effective_from",
                "scheduled_for",
            }:
                assert getattr(column["type"], "timezone", False), (
                    table_name,
                    column_name,
                )

    numeric_columns = {
        ("portfolio_snapshot", "cash"),
        ("portfolio_snapshot", "nav"),
        ("position", "core_quantity"),
        ("position", "tactical_quantity"),
        ("position", "avg_cost"),
        ("trade_record", "price"),
        ("decision_execution", "requested_quantity"),
    }
    for table_name, column_name in numeric_columns:
        columns = schema[table_name][1]
        column = next(item for item in columns if item["name"] == column_name)
        assert str(column["type"]).startswith("NUMERIC"), (table_name, column_name)
