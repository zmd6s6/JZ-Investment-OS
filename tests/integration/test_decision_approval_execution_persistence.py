"""PostgreSQL persistence for immutable PR-07 approval and paper/manual execution receipts."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from investment_os.infrastructure.persistence.models import (
    DecisionApprovalRecord,
    DecisionExecutionRecord,
)
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork

NOW = datetime(2026, 9, 20, 6, 30, tzinfo=UTC)
HASH = "a" * 64


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed_decision(engine: AsyncEngine) -> dict[str, UUID]:
    ids = {
        "instrument": uuid4(),
        "policy": uuid4(),
        "policy_version": uuid4(),
        "portfolio": uuid4(),
        "strategy_version": uuid4(),
        "decision": uuid4(),
    }
    correlation_id = uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO instrument "
                "(id, symbol, exchange, asset_type, currency, lot_size, status, created_by, "
                "correlation_id) VALUES (:id, 'SYNTH07', 'TEST', 'EQUITY', 'USD', 1, 'ACTIVE', "
                "'pytest', :correlation_id)"
            ),
            {"id": ids["instrument"], "correlation_id": correlation_id},
        )
        await connection.execute(
            text(
                "INSERT INTO investment_policy "
                "(id, name, status, version, created_by, correlation_id) "
                "VALUES (:id, 'synthetic-pr07-policy', 'DRAFT', 1, 'pytest', :correlation_id)"
            ),
            {"id": ids["policy"], "correlation_id": correlation_id},
        )
        await connection.execute(
            text(
                "INSERT INTO investment_policy_version "
                "(id, policy_id, version, config_json, content_hash, created_by, correlation_id) "
                "VALUES (:id, :policy_id, 1, '{}'::jsonb, :hash, 'pytest', :correlation_id)"
            ),
            {
                "id": ids["policy_version"],
                "policy_id": ids["policy"],
                "hash": HASH,
                "correlation_id": correlation_id,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO portfolio "
                "(id, base_currency, status, policy_id, created_by, correlation_id) "
                "VALUES (:id, 'USD', 'ACTIVE', :policy_id, 'pytest', :correlation_id)"
            ),
            {
                "id": ids["portfolio"],
                "policy_id": ids["policy"],
                "correlation_id": correlation_id,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO strategy_version "
                "(id, version, status, rules_json, prompt_bundle_hash, code_ref, content_hash, "
                "created_by, correlation_id) VALUES (:id, 1, 'DRAFT', '{}'::jsonb, :hash, "
                "'synthetic-pr07', :hash, 'pytest', :correlation_id)"
            ),
            {"id": ids["strategy_version"], "hash": HASH, "correlation_id": correlation_id},
        )
        await connection.execute(
            text(
                "INSERT INTO investment_decision "
                "(id, instrument_id, portfolio_id, policy_version_id, strategy_version_id, action, "
                "confidence, risk_intent, core_action, tactical_action, state, reasons_json, "
                "risks_json, watch_conditions_json, invalidation_conditions_json, next_review_at, "
                "input_snapshot_hash, "
                "version, created_by, correlation_id) VALUES (:id, :instrument_id, :portfolio_id, "
                ":policy_version_id, :strategy_version_id, 'BUY', 0.7, 'SMALL', 'BUY', 'NONE', "
                "'PENDING_APPROVAL', CAST(:reasons_json AS jsonb), "
                "'[]'::jsonb, '[]'::jsonb, '[]'::jsonb, :next_review_at, :hash, 1, 'pytest', "
                ":correlation_id)"
            ),
            {
                "id": ids["decision"],
                "instrument_id": ids["instrument"],
                "portfolio_id": ids["portfolio"],
                "policy_version_id": ids["policy_version"],
                "strategy_version_id": ids["strategy_version"],
                "next_review_at": NOW + timedelta(days=1),
                "hash": HASH,
                "reasons_json": '[{"text":"synthetic","evidence_ids":[]}]',
                "correlation_id": correlation_id,
            },
        )
    return ids


@pytest.mark.integration
async def test_approval_and_paper_execution_are_append_only_and_linked(
    database_engine: AsyncEngine,
) -> None:
    ids = await _seed_decision(database_engine)
    approval_id = uuid4()
    execution_id = uuid4()
    correlation_id = uuid4()

    async with SqlAlchemyUnitOfWork(_factory(database_engine)) as uow:
        await uow.decision_approvals.append(
            DecisionApprovalRecord(
                id=approval_id,
                decision_id=ids["decision"],
                actor_id="synthetic-owner",
                action="APPROVE",
                comment="Synthetic explicit approval.",
                expires_at=NOW + timedelta(hours=24),
                created_by="pytest",
                correlation_id=correlation_id,
                metadata_json={},
            )
        )
        await uow.decision_executions.append(
            DecisionExecutionRecord(
                id=execution_id,
                decision_id=ids["decision"],
                approval_id=approval_id,
                execution_mode="PAPER",
                status="FILLED",
                requested_quantity=Decimal("4"),
                filled_quantity=Decimal("4"),
                avg_price=Decimal("12.50"),
                external_refs_json=[],
                created_by="pytest",
                correlation_id=correlation_id,
                metadata_json={},
            )
        )
        await uow.commit()

    async with _factory(database_engine)() as session:
        approval = await session.get(DecisionApprovalRecord, approval_id)
        execution = await session.get(DecisionExecutionRecord, execution_id)
    assert approval is not None and approval.actor_id == "synthetic-owner"
    assert execution is not None and execution.approval_id == approval_id
    assert execution.execution_mode == "PAPER"
    assert execution.filled_quantity == Decimal("4")

    for table_name, record_id, assignment in (
        ("decision_approval", approval_id, "comment = 'mutated'"),
        ("decision_execution", execution_id, "status = 'MUTATED'"),
    ):
        with pytest.raises(DBAPIError):
            async with database_engine.begin() as connection:
                await connection.execute(
                    text(f"UPDATE {table_name} SET {assignment} WHERE id = :id"), {"id": record_id}
                )
