from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.infrastructure.persistence.jobs import ReliableJobExecutor
from investment_os.infrastructure.persistence.locks import try_transaction_advisory_lock
from investment_os.infrastructure.persistence.models import (
    EventLogRecord,
    InvestmentPolicyRecord,
    OutboxEventRecord,
    TaskRunRecord,
)
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork

NOW = datetime(2026, 9, 17, 8, 0, tzinfo=UTC)
HASH = "a" * 64


def _session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _audit_values() -> dict[str, object]:
    return {"created_by": "pytest", "correlation_id": uuid4()}


async def _seed_governed_records(engine: AsyncEngine) -> dict[str, UUID]:
    identifiers = {
        "instrument": uuid4(),
        "policy": uuid4(),
        "policy_version": uuid4(),
        "strategy_version": uuid4(),
        "portfolio": uuid4(),
        "position": uuid4(),
        "thesis": uuid4(),
        "thesis_version": uuid4(),
        "decision": uuid4(),
    }
    common = _audit_values()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO instrument "
                "(id, symbol, exchange, asset_type, currency, lot_size, status, "
                "created_by, correlation_id) "
                "VALUES (:id, 'SYNTH', 'TEST', 'EQUITY', 'USD', 1, 'ACTIVE', "
                ":created_by, :correlation_id)"
            ),
            {"id": identifiers["instrument"], **common},
        )
        await connection.execute(
            text(
                "INSERT INTO investment_policy "
                "(id, name, status, version, created_by, correlation_id) "
                "VALUES (:id, 'synthetic-policy', 'DRAFT', 1, :created_by, :correlation_id)"
            ),
            {"id": identifiers["policy"], **common},
        )
        await connection.execute(
            text(
                "INSERT INTO investment_policy_version "
                "(id, policy_id, version, config_json, content_hash, created_by, correlation_id) "
                "VALUES (:id, :policy_id, 1, '{}'::jsonb, :content_hash, "
                ":created_by, :correlation_id)"
            ),
            {
                "id": identifiers["policy_version"],
                "policy_id": identifiers["policy"],
                "content_hash": HASH,
                **common,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO strategy_version "
                "(id, version, status, rules_json, prompt_bundle_hash, code_ref, content_hash, "
                "created_by, correlation_id) "
                "VALUES (:id, 1, 'DRAFT', '{}'::jsonb, :content_hash, 'synthetic', "
                ":content_hash, :created_by, :correlation_id)"
            ),
            {"id": identifiers["strategy_version"], "content_hash": HASH, **common},
        )
        await connection.execute(
            text(
                "INSERT INTO portfolio "
                "(id, base_currency, status, policy_id, created_by, correlation_id) "
                "VALUES (:id, 'USD', 'ACTIVE', :policy_id, :created_by, :correlation_id)"
            ),
            {
                "id": identifiers["portfolio"],
                "policy_id": identifiers["policy"],
                **common,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO position "
                "(id, portfolio_id, instrument_id, core_quantity, tactical_quantity, "
                "avg_cost, realized_pnl, version, created_by, correlation_id) "
                "VALUES (:id, :portfolio_id, :instrument_id, 10, 2, 100, 0, 1, "
                ":created_by, :correlation_id)"
            ),
            {
                "id": identifiers["position"],
                "portfolio_id": identifiers["portfolio"],
                "instrument_id": identifiers["instrument"],
                **common,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO investment_thesis "
                "(id, instrument_id, status, version, created_by, correlation_id) "
                "VALUES (:id, :instrument_id, 'UNKNOWN', 1, :created_by, :correlation_id)"
            ),
            {"id": identifiers["thesis"], "instrument_id": identifiers["instrument"], **common},
        )
        await connection.execute(
            text(
                "INSERT INTO thesis_version "
                "(id, thesis_id, version, thesis_state, summary, pillars_json, catalysts_json, "
                "risks_json, invalidation_conditions_json, monitoring_conditions_json, "
                "change_reason, content_hash, created_by, correlation_id) "
                "VALUES (:id, :thesis_id, 1, 'UNKNOWN', 'synthetic', '[]'::jsonb, '[]'::jsonb, "
                "'[]'::jsonb, '[]'::jsonb, '[]'::jsonb, 'HUMAN_CORRECTION', :content_hash, "
                ":created_by, :correlation_id)"
            ),
            {
                "id": identifiers["thesis_version"],
                "thesis_id": identifiers["thesis"],
                "content_hash": HASH,
                **common,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO investment_decision "
                "(id, instrument_id, portfolio_id, policy_version_id, strategy_version_id, "
                "action, confidence, risk_intent, core_action, tactical_action, state, "
                "reasons_json, risks_json, watch_conditions_json, invalidation_conditions_json, "
                "next_review_at, input_snapshot_hash, version, created_by, correlation_id) "
                "VALUES (:id, :instrument_id, :portfolio_id, :policy_version_id, "
                ":strategy_version_id, 'WATCH', 0.5, 'NONE', 'NONE', 'NONE', 'DRAFT', "
                "'[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, :next_review_at, "
                ":input_hash, 1, :created_by, :correlation_id)"
            ),
            {
                "id": identifiers["decision"],
                "instrument_id": identifiers["instrument"],
                "portfolio_id": identifiers["portfolio"],
                "policy_version_id": identifiers["policy_version"],
                "strategy_version_id": identifiers["strategy_version"],
                "next_review_at": NOW,
                "input_hash": HASH,
                **common,
            },
        )
    return identifiers


def _policy(name: str, correlation_id: UUID) -> InvestmentPolicyRecord:
    return InvestmentPolicyRecord(
        name=name,
        status="DRAFT",
        version=1,
        created_by="pytest",
        correlation_id=correlation_id,
        causation_id=None,
        metadata_json={},
    )


def _event(correlation_id: UUID) -> EventLogRecord:
    return EventLogRecord(
        event_type="SyntheticCreated",
        aggregate_type="investment_policy",
        aggregate_id=uuid4(),
        payload_json={"synthetic": True},
        occurred_at=NOW,
        correlation_id=correlation_id,
        causation_id=None,
        schema_version="1.0",
        metadata_json={},
        created_by="pytest",
    )


def _outbox(event: EventLogRecord, correlation_id: UUID) -> OutboxEventRecord:
    return OutboxEventRecord(
        event_id=event.id,
        topic="synthetic.created",
        payload_json={"event_id": str(event.id)},
        attempts=0,
        created_by="pytest",
        correlation_id=correlation_id,
        causation_id=event.id,
        metadata_json={},
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stale_writes_fail_for_all_governed_optimistic_locks(
    database_engine: AsyncEngine,
) -> None:
    ids = await _seed_governed_records(database_engine)
    factory = _session_factory(database_engine)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.positions.update_quantities(
            ids["position"],
            expected_version=1,
            core_quantity=Decimal("11"),
            tactical_quantity=Decimal("2"),
        )
        await uow.theses.update_current_version(
            ids["thesis"],
            expected_version=1,
            current_version_id=ids["thesis_version"],
            status="VALID",
        )
        await uow.decisions.update_state(ids["decision"], expected_version=1, state="VALIDATED")
        await uow.policies.activate_version(
            ids["policy"],
            expected_version=1,
            current_version_id=ids["policy_version"],
        )
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as stale:
        operations = (
            stale.positions.update_quantities(
                ids["position"],
                expected_version=1,
                core_quantity=Decimal("12"),
                tactical_quantity=Decimal("2"),
            ),
            stale.theses.update_current_version(
                ids["thesis"],
                expected_version=1,
                current_version_id=ids["thesis_version"],
                status="VALID",
            ),
            stale.decisions.update_state(ids["decision"], expected_version=1, state="VALIDATED"),
            stale.policies.activate_version(
                ids["policy"],
                expected_version=1,
                current_version_id=ids["policy_version"],
            ),
        )
        for operation in operations:
            with pytest.raises(ApplicationError) as captured:
                await operation
            assert captured.value.code is ApplicationErrorCode.OPTIMISTIC_CONCURRENCY_CONFLICT


@pytest.mark.integration
@pytest.mark.asyncio
async def test_successful_job_commits_business_event_and_outbox_once(
    database_engine: AsyncEngine,
) -> None:
    factory = _session_factory(database_engine)
    executor = ReliableJobExecutor(factory, now=lambda: NOW)
    correlation_id = uuid4()
    invocations = 0

    async def handler(uow: SqlAlchemyUnitOfWork) -> None:
        nonlocal invocations
        invocations += 1
        await uow.policies.add(_policy("atomic-success", correlation_id))
        event = _event(correlation_id)
        await uow.events.append(event)
        await uow.outbox.add(_outbox(event, correlation_id))

    first = await executor.execute(
        task_name="synthetic",
        scheduled_for=NOW,
        idempotency_key="synthetic:success",
        input_hash=HASH,
        handler=handler,
        correlation_id=correlation_id,
    )
    repeated = await executor.execute(
        task_name="synthetic",
        scheduled_for=NOW,
        idempotency_key="synthetic:success",
        input_hash=HASH,
        handler=handler,
        correlation_id=correlation_id,
    )

    async with factory() as session:
        policy_count = await session.scalar(
            select(func.count()).select_from(InvestmentPolicyRecord)
        )
        outbox_count = await session.scalar(select(func.count()).select_from(OutboxEventRecord))
        task = (
            await session.scalars(
                select(TaskRunRecord).where(TaskRunRecord.idempotency_key == "synthetic:success")
            )
        ).one()

    assert invocations == 1
    assert policy_count == 1
    assert outbox_count == 1
    assert task.status == "SUCCEEDED"
    assert task.attempt == 1
    assert first.reused is False
    assert repeated.reused is True
    assert repeated.task_run_id == first.task_run_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_failed_job_rolls_back_business_and_outbox_but_records_sanitized_failure(
    database_engine: AsyncEngine,
) -> None:
    factory = _session_factory(database_engine)
    executor = ReliableJobExecutor(factory, now=lambda: NOW)
    correlation_id = uuid4()

    async def handler(uow: SqlAlchemyUnitOfWork) -> None:
        await uow.policies.add(_policy("must-rollback", correlation_id))
        event = _event(correlation_id)
        await uow.events.append(event)
        await uow.outbox.add(_outbox(event, correlation_id))
        raise ValueError("sensitive fixture text must not be persisted")

    with pytest.raises(ValueError, match="sensitive fixture"):
        await executor.execute(
            task_name="synthetic",
            scheduled_for=NOW,
            idempotency_key="synthetic:failure",
            input_hash=HASH,
            handler=handler,
            correlation_id=correlation_id,
        )

    async with factory() as session:
        policy_count = await session.scalar(
            select(func.count()).select_from(InvestmentPolicyRecord)
        )
        event_count = await session.scalar(select(func.count()).select_from(EventLogRecord))
        outbox_count = await session.scalar(select(func.count()).select_from(OutboxEventRecord))
        task = (
            await session.scalars(
                select(TaskRunRecord).where(TaskRunRecord.idempotency_key == "synthetic:failure")
            )
        ).one()

    assert policy_count == 0
    assert event_count == 0
    assert outbox_count == 0
    assert task.status == "FAILED"
    assert task.attempt == 1
    assert task.error_json == {"code": "JOB_HANDLER_FAILED", "type": "ValueError"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_transaction_advisory_lock_rejects_concurrent_logical_job(
    database_engine: AsyncEngine,
) -> None:
    factory = _session_factory(database_engine)
    async with factory() as first, factory() as second:
        assert await try_transaction_advisory_lock(
            first, namespace="task_run", logical_key="same-job"
        )
        assert not await try_transaction_advisory_lock(
            second, namespace="task_run", logical_key="same-job"
        )
        await first.rollback()
        assert await try_transaction_advisory_lock(
            second, namespace="task_run", logical_key="same-job"
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_executor_rejects_lock_contention_and_idempotency_input_drift(
    database_engine: AsyncEngine,
) -> None:
    factory = _session_factory(database_engine)
    executor = ReliableJobExecutor(factory, now=lambda: NOW)

    async def handler(uow: SqlAlchemyUnitOfWork) -> None:
        await uow.policies.add(_policy("idempotency-boundary", uuid4()))

    async with factory() as lock_holder:
        assert await try_transaction_advisory_lock(
            lock_holder, namespace="task_run", logical_key="synthetic:boundary"
        )
        with pytest.raises(ApplicationError) as locked:
            await executor.execute(
                task_name="synthetic",
                scheduled_for=NOW,
                idempotency_key="synthetic:boundary",
                input_hash=HASH,
                handler=handler,
            )
        assert locked.value.code is ApplicationErrorCode.JOB_ALREADY_RUNNING
        await lock_holder.rollback()

    await executor.execute(
        task_name="synthetic",
        scheduled_for=NOW,
        idempotency_key="synthetic:boundary",
        input_hash=HASH,
        handler=handler,
    )
    with pytest.raises(ApplicationError) as drift:
        await executor.execute(
            task_name="synthetic",
            scheduled_for=NOW,
            idempotency_key="synthetic:boundary",
            input_hash="b" * 64,
            handler=handler,
        )
    assert drift.value.code is ApplicationErrorCode.IDEMPOTENCY_KEY_CONFLICT


@pytest.mark.integration
@pytest.mark.asyncio
async def test_outbox_claim_publish_and_failure_bookkeeping(database_engine: AsyncEngine) -> None:
    factory = _session_factory(database_engine)
    correlation_id = uuid4()
    event = _event(correlation_id)
    second_event = _event(correlation_id)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.events.append(event)
        first = _outbox(event, correlation_id)
        await uow.outbox.add(first)
        await uow.events.append(second_event)
        second = _outbox(second_event, correlation_id)
        await uow.outbox.add(second)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        claimed = await uow.outbox.unpublished(limit=1)
        assert len(claimed) == 1
        failed_id = claimed[0].id
        await uow.outbox.record_failure(claimed[0].id, error_code="DELIVERY_TIMEOUT")
        await uow.commit()

    publish_id = second.id if failed_id == first.id else first.id
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.outbox.mark_published(publish_id, published_at=NOW)
        with pytest.raises(LookupError):
            await uow.outbox.mark_published(uuid4(), published_at=NOW)
        with pytest.raises(LookupError):
            await uow.outbox.record_failure(uuid4(), error_code="UNKNOWN")
        await uow.commit()

    async with factory() as session:
        published = await session.get(OutboxEventRecord, publish_id)
        failed = await session.get(OutboxEventRecord, failed_id)
    assert published is not None
    assert published.published_at == NOW
    assert published.attempts >= 1
    assert failed is not None
    assert failed.published_at is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_job_rejects_naive_business_time(database_engine: AsyncEngine) -> None:
    executor = ReliableJobExecutor(_session_factory(database_engine), now=lambda: NOW)

    async def handler(_: SqlAlchemyUnitOfWork) -> None:
        raise AssertionError("handler must not run")

    with pytest.raises(ValueError, match="timezone-aware"):
        await executor.execute(
            task_name="synthetic",
            scheduled_for=datetime(2026, 9, 17),
            idempotency_key="synthetic:naive-time",
            input_hash=HASH,
            handler=handler,
        )
