"""Integration coverage for append-only Agent and committee observability."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from investment_os.application.agent_registry import AgentRoleRegistry, PromptBundle
from investment_os.application.agent_runtime import AgentRuntime
from investment_os.application.analysis_context import AnalysisEvidence, freeze_analysis_context
from investment_os.application.committee import ROUND_ONE_ROLES
from investment_os.application.committee_runtime import CommitteeRoleInput, CommitteeRuntime
from investment_os.application.errors import ApplicationError
from investment_os.application.llm_gateway import (
    LLMGatewayRequest,
    LLMGatewayResponse,
    SyntheticLLMGateway,
)
from investment_os.domain.agent import AgentRole, AgentTool
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.agent_observability_writer import (
    SqlAlchemyCommitteeObservabilityWriter,
)
from investment_os.infrastructure.persistence.models import (
    AgentOpinionRecord,
    AgentRunRecord,
    CommitteeMessageRecord,
    CommitteeSessionRecord,
    ConflictRecord,
)
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork

NOW = datetime(2026, 9, 19, 0, 0, tzinfo=UTC)
HASH = "a" * 64


def _session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed_instrument(engine: AsyncEngine) -> UUID:
    instrument_id = uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO instrument "
                "(id, symbol, exchange, asset_type, currency, lot_size, status, "
                "created_by, correlation_id) "
                "VALUES (:id, 'SYNTH', 'TEST', 'EQUITY', 'USD', 1, 'ACTIVE', "
                "'pytest', :correlation_id)"
            ),
            {"id": instrument_id, "correlation_id": uuid4()},
        )
    return instrument_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_and_committee_observability_is_append_only_and_sanitized(
    database_engine: AsyncEngine,
) -> None:
    instrument_id = await _seed_instrument(database_engine)
    correlation_id = uuid4()
    session_id = uuid4()
    run_id = uuid4()
    opinion_id = uuid4()
    message_id = uuid4()
    conflict_id = uuid4()
    factory = _session_factory(database_engine)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.agent_observability.append_session(
            CommitteeSessionRecord(
                id=session_id,
                instrument_id=instrument_id,
                session_type="SYNTHETIC_TEST",
                round_count=2,
                status="COMPLETED",
                input_snapshot_hash=HASH,
                started_at=NOW,
                completed_at=NOW,
                created_by="pytest",
                correlation_id=correlation_id,
                metadata_json={"protocol_version": "v1"},
            )
        )
        await uow.agent_observability.append_run(
            AgentRunRecord(
                id=run_id,
                agent_role="MACRO",
                model_provider="synthetic",
                model_name="fixture-v1",
                prompt_version="v1",
                input_snapshot_hash=HASH,
                started_at=NOW,
                ended_at=NOW,
                status="SUCCEEDED",
                token_usage_json={"input": 1, "output": 1},
                error_code=None,
                created_by="pytest",
                correlation_id=correlation_id,
                metadata_json={
                    "prompt_bundle_hash": HASH,
                    "raw_output_hashes": ["b" * 64],
                    "repair_count": 0,
                    "latency_ms": 1,
                },
            )
        )
        await uow.agent_observability.append_opinion(
            AgentOpinionRecord(
                id=opinion_id,
                agent_run_id=run_id,
                instrument_id=instrument_id,
                stance="INSUFFICIENT_DATA",
                confidence=Decimal("0"),
                time_horizon="synthetic horizon",
                observations_json=[],
                thesis_impacts_json=[],
                assumptions_json=[],
                risks_json=[],
                invalidation_conditions_json=[],
                unknowns_json=["GATEWAY_FAILURE"],
                content_hash="c" * 64,
                created_by="pytest",
                correlation_id=correlation_id,
            )
        )
        await uow.agent_observability.append_message(
            CommitteeMessageRecord(
                id=message_id,
                session_id=session_id,
                round_number=2,
                agent_role="DEVILS_ADVOCATE",
                message_type="SYNTHETIC_REBUTTAL",
                opinion_id=opinion_id,
                targets_opinion_id=None,
                payload_json={"opinion_hash": "c" * 64},
                created_by="pytest",
                correlation_id=correlation_id,
            )
        )
        await uow.agent_observability.append_conflict(
            ConflictRecord(
                id=conflict_id,
                session_id=session_id,
                conflict_type="STANCE_SPREAD",
                severity="MATERIAL",
                opinion_ids=[str(opinion_id)],
                question="Resolve the synthetic disagreement through bounded review.",
                resolution=None,
                created_by="pytest",
                correlation_id=correlation_id,
                metadata_json={"protocol_version": "v1"},
            )
        )
        await uow.commit()

    async with factory() as session:
        run = await session.get(AgentRunRecord, run_id)
        message_count = await session.scalar(
            select(func.count())
            .select_from(CommitteeMessageRecord)
            .where(CommitteeMessageRecord.session_id == session_id)
        )
        conflict = await session.get(ConflictRecord, conflict_id)

    assert run is not None
    assert run.metadata_json["raw_output_hashes"] == ["b" * 64]
    assert "raw_output" not in run.metadata_json
    assert message_count == 1
    assert conflict is not None
    assert conflict.resolution is None

    for table_name, record_id in (("agent_run", run_id), ("committee_session", session_id)):
        with pytest.raises(DBAPIError):
            async with database_engine.begin() as connection:
                await connection.execute(
                    text(f"UPDATE {table_name} SET status = 'ALTERED' WHERE id = :id"),
                    {"id": record_id},
                )
    with pytest.raises(DBAPIError):
        async with database_engine.begin() as connection:
            await connection.execute(
                text("UPDATE conflict_record SET severity = 'ALTERED' WHERE id = :id"),
                {"id": conflict_id},
            )


def _response(*, role: AgentRole, instrument_id: UUID, evidence_id: UUID) -> LLMGatewayResponse:
    return LLMGatewayResponse(
        raw_output=(
            "{"
            '"schema_version":"v1",'
            f'"role":"{role.value}",'
            f'"instrument_id":"{instrument_id}",'
            '"stance":"MIXED",'
            '"confidence":"0.5",'
            '"time_horizon":"synthetic horizon",'
            '"observations":[{'
            '"statement":"Synthetic evidence-backed fact",'
            f'"evidence_ids":["{evidence_id}"]'
            "}],"
            '"assumptions":[],"unknowns":[],"risks":[]'
            "}"
        ),
        provider="synthetic",
        model_name="fixture-v1",
        latency_ms=1,
        input_tokens=1,
        output_tokens=1,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_completed_committee_runtime_persists_all_observability_atomically(
    database_engine: AsyncEngine,
) -> None:
    instrument_id = await _seed_instrument(database_engine)
    evidence = AnalysisEvidence(
        evidence_id=uuid4(), content_hash="d" * 64, available_at=UtcTimestamp(NOW)
    )
    context = freeze_analysis_context(instrument_id, as_of=NOW, evidence=(evidence,))
    roles = (*ROUND_ONE_ROLES, AgentRole.DEVILS_ADVOCATE)
    registry = AgentRoleRegistry(
        tuple(
            PromptBundle(
                role=role,
                version="v1",
                content_hash=HASH,
                allowed_tools=(AgentTool.RETRIEVE_EVIDENCE,),
            )
            for role in roles
        )
    )
    gateway = SyntheticLLMGateway(
        tuple(
            _response(role=role, instrument_id=instrument_id, evidence_id=evidence.evidence_id)
            for role in roles
        )
    )
    runtime = CommitteeRuntime(agent_runtime=AgentRuntime(registry=registry, gateway=gateway))

    def request_factory(role: AgentRole, role_input: CommitteeRoleInput) -> LLMGatewayRequest:
        return LLMGatewayRequest(
            request_id=uuid4(),
            role=role,
            prompt_bundle_hash=HASH,
            input_snapshot_hash=role_input.context.input_snapshot_hash,
            timeout_seconds=30,
            max_output_tokens=300,
            committee_context_hash=role_input.content_hash,
        )

    result = await runtime.run_session(context=context, request_factory=request_factory)
    write_result = await SqlAlchemyCommitteeObservabilityWriter(
        _session_factory(database_engine), now=lambda: NOW
    ).persist(
        result=result,
        context=context,
        registry=registry,
        started_at=NOW,
        correlation_id=uuid4(),
    )

    async with _session_factory(database_engine)() as session:
        run_count = await session.scalar(
            select(func.count())
            .select_from(AgentRunRecord)
            .where(AgentRunRecord.id.in_(write_result.run_ids))
        )
        opinion_count = await session.scalar(
            select(func.count())
            .select_from(AgentOpinionRecord)
            .where(AgentOpinionRecord.id.in_(write_result.opinion_ids))
        )
        message_count = await session.scalar(
            select(func.count())
            .select_from(CommitteeMessageRecord)
            .where(CommitteeMessageRecord.session_id == write_result.session_id)
        )
        run_records = list(
            (
                await session.scalars(
                    select(AgentRunRecord).where(AgentRunRecord.id.in_(write_result.run_ids))
                )
            ).all()
        )

    assert len(result.rounds) == 2
    assert run_count == 6
    assert opinion_count == 6
    assert message_count == 6
    assert all("raw_output" not in record.metadata_json for record in run_records)
    with pytest.raises(ApplicationError, match="completion cannot precede"):
        await SqlAlchemyCommitteeObservabilityWriter(
            _session_factory(database_engine), now=lambda: NOW
        ).persist(
            result=result,
            context=context,
            registry=registry,
            started_at=NOW,
            completed_at=NOW - timedelta(microseconds=1),
        )
