"""PostgreSQL persistence for immutable PR-07 approval and paper/manual execution receipts."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from investment_os.api.app import create_app
from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.domain.approval import DecisionApproval
from investment_os.domain.decision import DecisionClaim, DecisionPosition, InvestmentDecision
from investment_os.domain.enums import (
    Action,
    ApprovalAction,
    BucketAction,
    DecisionState,
    ExecutionMode,
    ExecutionStatus,
    RiskIntent,
)
from investment_os.domain.execution import DecisionExecution
from investment_os.domain.values import Quantity, UtcTimestamp, Weight
from investment_os.infrastructure.decision_journal import (
    SqlAlchemyDecisionJournalReader,
    SqlAlchemyDecisionJournalWriter,
)
from investment_os.infrastructure.persistence.models import (
    DecisionApprovalRecord,
    DecisionExecutionRecord,
    EvidenceRecord,
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
        "thesis": uuid4(),
        "thesis_version": uuid4(),
        "committee": uuid4(),
        "risk": uuid4(),
        "sizing": uuid4(),
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
                "INSERT INTO investment_thesis "
                "(id, instrument_id, status, version, created_by, correlation_id) "
                "VALUES (:id, :instrument_id, 'VALID', 1, 'pytest', :correlation_id)"
            ),
            {
                "id": ids["thesis"],
                "instrument_id": ids["instrument"],
                "correlation_id": correlation_id,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO thesis_version "
                "(id, thesis_id, version, thesis_state, summary, pillars_json, catalysts_json, "
                "risks_json, invalidation_conditions_json, monitoring_conditions_json, "
                "change_reason, content_hash, created_by, correlation_id) "
                "VALUES (:id, :thesis_id, 1, 'VALID', 'synthetic thesis', '{}'::jsonb, "
                "'[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, 'NEW_EVIDENCE', :hash, "
                "'pytest', :correlation_id)"
            ),
            {
                "id": ids["thesis_version"],
                "thesis_id": ids["thesis"],
                "hash": HASH,
                "correlation_id": correlation_id,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO committee_session "
                "(id, instrument_id, session_type, round_count, status, input_snapshot_hash, "
                "started_at, created_by, correlation_id) VALUES "
                "(:id, :instrument_id, 'SYNTHETIC', 1, 'COMPLETED', :hash, :started_at, "
                "'pytest', :correlation_id)"
            ),
            {
                "id": ids["committee"],
                "instrument_id": ids["instrument"],
                "hash": HASH,
                "started_at": NOW,
                "correlation_id": correlation_id,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO risk_assessment "
                "(id, session_id, veto, veto_codes, hard_flags_json, soft_flags_json, expires_at, "
                "content_hash, created_by, correlation_id) VALUES "
                "(:id, :session_id, false, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, :expires_at, "
                ":hash, 'pytest', :correlation_id)"
            ),
            {
                "id": ids["risk"],
                "session_id": ids["committee"],
                "expires_at": NOW + timedelta(days=1),
                "hash": HASH,
                "correlation_id": correlation_id,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO position_sizing_run "
                "(id, portfolio_id, instrument_id, policy_version_id, input_json, formula_version, "
                "output_json, input_hash, created_by, correlation_id) VALUES "
                "(:id, :portfolio_id, :instrument_id, :policy_version_id, '{}'::jsonb, "
                "'synthetic-pr07-formula-v1', '{}'::jsonb, :hash, 'pytest', :correlation_id)"
            ),
            {
                "id": ids["sizing"],
                "portfolio_id": ids["portfolio"],
                "instrument_id": ids["instrument"],
                "policy_version_id": ids["policy_version"],
                "hash": HASH,
                "correlation_id": correlation_id,
            },
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


async def _append_evidence(
    engine: AsyncEngine,
    *,
    instrument_id: UUID,
    available_at: datetime,
) -> UUID:
    evidence_id = uuid4()
    async with _factory(engine)() as session:
        session.add(
            EvidenceRecord(
                id=evidence_id,
                instrument_id=instrument_id,
                evidence_type="EVENT",
                source_name="synthetic-pr07-provider",
                source_locator=f"synthetic://pr07/{evidence_id}",
                source_tier="PRIMARY",
                observed_at=available_at,
                effective_at=available_at,
                available_at=available_at,
                ingested_at=available_at,
                quality_score=Decimal("0.95"),
                freshness_status="FRESH",
                payload_json={"synthetic": True},
                content_hash=HASH,
                created_by="pytest",
                correlation_id=uuid4(),
                causation_id=None,
                metadata_json={},
            )
        )
        await session.commit()
    return evidence_id


def _decision(ids: dict[str, UUID], evidence_id: UUID) -> InvestmentDecision:
    zero = Weight(Decimal("0"))
    tenth = Weight(Decimal("0.1"))
    return InvestmentDecision(
        instrument_id=ids["instrument"],
        portfolio_id=ids["portfolio"],
        thesis_version_id=ids["thesis_version"],
        policy_version_id=ids["policy_version"],
        strategy_version_id=ids["strategy_version"],
        risk_assessment_id=ids["risk"],
        position_sizing_run_id=ids["sizing"],
        action=Action.BUY,
        confidence=Weight(Decimal("0.7")),
        risk_intent=RiskIntent.SMALL,
        position_before=DecisionPosition(total=zero, core=zero, tactical=zero),
        position_after_proposed=DecisionPosition(total=tenth, core=tenth, tactical=zero),
        core_action=BucketAction.BUY,
        tactical_action=BucketAction.NONE,
        reasons=(DecisionClaim("Synthetic audited reason", (evidence_id,)),),
        risks=(DecisionClaim("Synthetic audited risk", (evidence_id,)),),
        watch_conditions=("Review synthetic inputs daily",),
        invalidation_conditions=("Synthetic demand deterioration",),
        unknowns=("Synthetic valuation uncertainty",),
        dissent=("Synthetic timing dissent",),
        next_review_at=UtcTimestamp(NOW + timedelta(days=1)),
        input_snapshot_hash=HASH,
        prompt_bundle_version="synthetic-pr07-prompt-v1",
        formula_version="synthetic-pr07-formula-v1",
        committee_session_id=ids["committee"],
        state=DecisionState.PENDING_APPROVAL,
    )


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


@pytest.mark.integration
async def test_decision_journal_api_reconstructs_immutable_approval_and_execution_chain(
    database_engine: AsyncEngine,
) -> None:
    ids = await _seed_decision(database_engine)
    approval_id = uuid4()
    execution_id = uuid4()
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
                correlation_id=uuid4(),
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
                correlation_id=uuid4(),
                metadata_json={},
            )
        )
        await uow.commit()

    app = create_app(
        decision_journal_reader=SqlAlchemyDecisionJournalReader(_factory(database_engine))
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/decisions/{ids['decision']}")
        missing = await client.get(f"/api/v1/decisions/{uuid4()}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision_id"] == str(ids["decision"])
    assert payload["content_hash"] == "0" * 64
    assert payload["approvals"] == [
        {
            "id": str(approval_id),
            "actor_id": "synthetic-owner",
            "action": "APPROVE",
            "comment": "Synthetic explicit approval.",
            "expires_at": (NOW + timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
            "occurred_at": payload["approvals"][0]["occurred_at"],
        }
    ]
    assert payload["executions"][0]["id"] == str(execution_id)
    assert payload["executions"][0]["execution_mode"] == "PAPER"
    assert Decimal(payload["executions"][0]["filled_quantity"]) == Decimal("4")
    assert missing.status_code == 404


@pytest.mark.integration
async def test_s10_reconstructs_synthetic_evidence_decision_approval_and_paper_execution(
    database_engine: AsyncEngine,
) -> None:
    """S10: a valid named approval is required before the paper receipt becomes audit history."""

    ids = await _seed_decision(database_engine)
    evidence_id = await _append_evidence(
        database_engine,
        instrument_id=ids["instrument"],
        available_at=NOW,
    )
    writer = SqlAlchemyDecisionJournalWriter(_factory(database_engine))
    decision = _decision(ids, evidence_id)

    persisted = await writer.append_decision(decision, recorded_at=NOW)
    approval = DecisionApproval(
        decision_id=decision.id,
        actor_id="synthetic-owner",
        action=ApprovalAction.APPROVE,
        occurred_at=UtcTimestamp(NOW + timedelta(minutes=1)),
        expires_at=UtcTimestamp(NOW + timedelta(hours=24)),
        comment="Synthetic explicit approval.",
    )
    await writer.append_approval(approval)
    execution = DecisionExecution(
        decision_id=decision.id,
        approval=approval,
        mode=ExecutionMode.PAPER,
        status=ExecutionStatus.FILLED,
        requested_quantity=Quantity(Decimal("4")),
        filled_quantity=Quantity(Decimal("4")),
        recorded_at=UtcTimestamp(NOW + timedelta(minutes=2)),
        average_price=Decimal("12.50"),
    )
    await writer.append_execution(execution)

    app = create_app(
        decision_journal_reader=SqlAlchemyDecisionJournalReader(_factory(database_engine))
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/decisions/{decision.id}")

    assert persisted.decision_id == decision.id
    assert persisted.content_hash == decision.content_hash
    assert response.status_code == 200
    journal = response.json()
    assert journal["evidence_ids"] == [str(evidence_id)]
    assert journal["reasons"][0]["evidence_ids"] == [str(evidence_id)]
    assert journal["approvals"][0]["id"] == str(approval.id)
    assert journal["executions"][0]["approval_id"] == str(approval.id)
    assert journal["executions"][0]["execution_mode"] == "PAPER"


@pytest.mark.integration
async def test_decision_writer_rejects_evidence_unavailable_at_its_recorded_time(
    database_engine: AsyncEngine,
) -> None:
    ids = await _seed_decision(database_engine)
    future_evidence_id = await _append_evidence(
        database_engine,
        instrument_id=ids["instrument"],
        available_at=NOW + timedelta(seconds=1),
    )
    decision = _decision(ids, future_evidence_id)

    with pytest.raises(ApplicationError) as error:
        await SqlAlchemyDecisionJournalWriter(_factory(database_engine)).append_decision(
            decision,
            recorded_at=NOW,
        )

    assert error.value.code is ApplicationErrorCode.EVIDENCE_REFERENCE_UNAVAILABLE
