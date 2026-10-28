"""Atomic persistence of real Feature, Agent and Committee artifacts linked to AnalysisRun."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.agent_registry import AgentRoleRegistry
from investment_os.application.agent_runtime import AgentRunAttempt, AgentRunResult
from investment_os.application.analysis_context import AnalysisContext
from investment_os.application.analysis_runs import AnalysisFrozenInput, AnalysisQueuedInput
from investment_os.application.committee_runtime import CommitteeRoundResult, CommitteeSessionResult
from investment_os.application.evidence import FeatureSnapshot
from investment_os.application.investment_analysis import PROMPT_VERSION, opinion_summary
from investment_os.application.llm_gateway import LLMGatewayPort, LLMGatewayRequest
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.infrastructure.analysis_inputs import (
    AnalysisGatewayFactory,
    SqlAnalysisInputPreparer,
)
from investment_os.infrastructure.analysis_runs import append_step, audit, locked
from investment_os.infrastructure.persistence.agent_observability import (
    agent_opinion_record_from_result,
    agent_run_record_from_result,
    committee_message_records_from_result,
    committee_session_record_from_result,
    conflict_records_from_result,
)
from investment_os.infrastructure.persistence.analysis_models import (
    AnalysisRoleOutputRecord,
    AnalysisStepRecord,
)
from investment_os.infrastructure.persistence.models import AgentRunRecord, FeatureSnapshotRecord
from investment_os.infrastructure.persistence.repositories import AgentObservabilityRepository


class SqlAnalysisExecution:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        preparer: SqlAnalysisInputPreparer,
        gateways: AnalysisGatewayFactory,
    ):
        self._sessions = sessions
        self._preparer = preparer
        self._gateways = gateways

    async def close(self) -> None:
        await self._gateways.close()

    async def prepare(
        self, run_id: UUID, lease: UUID, queued: AnalysisQueuedInput
    ) -> AnalysisFrozenInput:
        return await self._preparer.prepare(run_id, lease, queued)

    def gateway_for(self, run_id: UUID, lease: UUID, queued: AnalysisQueuedInput) -> LLMGatewayPort:
        return self._gateways.gateway_for(run_id, lease, queued)

    async def features(self, run_id: UUID, lease: UUID, snapshot: FeatureSnapshot) -> UUID:
        async with self._sessions() as session, session.begin():
            record = await locked(session, run_id, lease)
            feature = FeatureSnapshotRecord(
                instrument_id=snapshot.instrument_id,
                as_of=snapshot.as_of.value,
                feature_set_version=snapshot.feature_set_version,
                values_json=dict(snapshot.values),
                input_hash=snapshot.input_hash,
                **audit(run_id),
            )
            session.add(feature)
            await session.flush()
            await append_step(
                session,
                record,
                stage="FEATURES",
                status="COMPLETED",
                payload={
                    "feature_snapshot_id": str(feature.id),
                    "version": snapshot.feature_set_version,
                    "values": dict(snapshot.values),
                    "input_hash": snapshot.input_hash,
                },
            )
            return feature.id

    async def _save_agent(
        self,
        session: AsyncSession,
        run_id: UUID,
        request: LLMGatewayRequest,
        result: AgentRunResult,
        registry: AgentRoleRegistry,
        round_number: int,
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        stage = "RISK" if round_number == 0 else f"ROUND_{round_number}"
        started = await session.scalar(
            select(AnalysisStepRecord.occurred_at)
            .where(
                AnalysisStepRecord.run_id == run_id,
                AnalysisStepRecord.stage == stage,
                AnalysisStepRecord.status == "RUNNING",
            )
            .order_by(AnalysisStepRecord.sequence.desc())
            .limit(1)
        )
        run = agent_run_record_from_result(
            request=request,
            prompt_bundle=registry.require(request.role),
            result=result,
            started_at=started or now,
            ended_at=now,
            created_by="analysis_runtime",
            correlation_id=run_id,
        )
        if result.failure is not None and result.failure.value == "GATEWAY_FAILURE":
            run.token_usage_json = {**run.token_usage_json, "cost": None}
            run.metadata_json = {**run.metadata_json, "cost_unconfirmed": True}
        opinion = agent_opinion_record_from_result(
            agent_run_id=run.id, result=result, created_by="analysis_runtime", correlation_id=run_id
        )
        repository = AgentObservabilityRepository(session)
        await repository.append_run(run)
        await repository.append_opinion(opinion)
        payload: dict[str, object] = {
            "agent_run_id": str(run.id),
            "opinion_id": str(opinion.id),
            "summary": opinion_summary(result),
            "telemetry": run.metadata_json,
        }
        session.add(
            AnalysisRoleOutputRecord(
                run_id=run_id,
                role=request.role.value,
                round_number=round_number,
                schema_kind="agent-opinion-1.0",
                agent_run_id=run.id,
                payload_json=payload,
                content_hash=fingerprint(payload),
                **audit(run_id),
            )
        )
        return payload

    async def round_result(
        self,
        run_id: UUID,
        lease: UUID,
        context: AnalysisContext,
        result: CommitteeRoundResult,
        registry: AgentRoleRegistry,
    ) -> None:
        async with self._sessions() as session, session.begin():
            record = await locked(session, run_id, lease)
            roles = []
            for request, outcome in zip(result.requests, result.results, strict=True):
                roles.append(
                    await self._save_agent(
                        session, run_id, request, outcome, registry, result.plan.number
                    )
                )
            await append_step(
                session,
                record,
                stage=f"ROUND_{result.plan.number}",
                status="COMPLETED",
                payload={
                    "roles": roles,
                    "input_hash": context.input_snapshot_hash,
                    "conflict_count": len(result.plan.conflicts),
                },
            )

    async def agent_result(
        self,
        run_id: UUID,
        lease: UUID,
        context: AnalysisContext,
        request: LLMGatewayRequest,
        result: AgentRunResult,
        registry: AgentRoleRegistry,
    ) -> None:
        async with self._sessions() as session, session.begin():
            record = await locked(session, run_id, lease)
            payload = await self._save_agent(session, run_id, request, result, registry, 0)
            await append_step(
                session,
                record,
                stage="RISK_AGENT",
                status="COMPLETED" if result.failure is None else "FAILED",
                payload=payload,
                reason_code=result.failure.value if result.failure else None,
            )

    async def committee_result(
        self, run_id: UUID, lease: UUID, context: AnalysisContext, result: CommitteeSessionResult
    ) -> UUID:
        async with self._sessions() as session, session.begin():
            record = await locked(session, run_id, lease)
            outputs = (
                await session.scalars(
                    select(AnalysisRoleOutputRecord).where(
                        AnalysisRoleOutputRecord.run_id == run_id,
                        AnalysisRoleOutputRecord.round_number.in_((1, 2)),
                        AnalysisRoleOutputRecord.schema_kind == "agent-opinion-1.0",
                    )
                )
            ).all()
            opinions = {
                (output.round_number, output.role): UUID(str(output.payload_json["opinion_id"]))
                for output in outputs
            }
            committee = committee_session_record_from_result(
                result=result,
                context=context,
                started_at=record.started_at or record.queued_at,
                completed_at=datetime.now(UTC),
                created_by="analysis_runtime",
                correlation_id=run_id,
            )
            committee.metadata_json = {
                **committee.metadata_json,
                "analysis_run_id": str(run_id),
                "failed_role_count": sum(
                    bool(item.failure)
                    for round_result in result.rounds
                    for item in round_result.results
                ),
            }
            repository = AgentObservabilityRepository(session)
            await repository.append_session(committee)
            for message in committee_message_records_from_result(
                session_id=committee.id,
                result=result,
                opinion_ids=opinions,
                created_by="analysis_runtime",
                correlation_id=run_id,
            ):
                await repository.append_message(message)
            for conflict in conflict_records_from_result(
                session_id=committee.id,
                result=result,
                opinion_ids=opinions,
                created_by="analysis_runtime",
                correlation_id=run_id,
            ):
                await repository.append_conflict(conflict)
            await append_step(
                session,
                record,
                stage="COMMITTEE",
                status="COMPLETED",
                payload={
                    "committee_session_id": str(committee.id),
                    "round_count": 2,
                    "unresolved_conflicts": len(result.rounds[1].plan.conflicts),
                },
            )
            return committee.id

    async def role_result(
        self,
        run_id: UUID,
        lease: UUID,
        request: LLMGatewayRequest,
        payload: dict[str, object] | None,
        attempts: tuple[AgentRunAttempt, ...],
        failure: str | None,
    ) -> None:
        async with self._sessions() as session, session.begin():
            record = await locked(session, run_id, lease)
            last = attempts[-1] if attempts else None
            schema_kind = (
                "portfolio-intent-1.0" if request.role.value == "PORTFOLIO" else "cio-proposal-1.0"
            )
            telemetry = [
                {
                    "repair_attempt": item.repair_attempt,
                    "provider": item.provider,
                    "model_name": item.model_name,
                    "raw_output_hash": item.raw_output_hash,
                    "input_tokens": item.input_tokens,
                    "output_tokens": item.output_tokens,
                    "latency_ms": item.latency_ms,
                    "cost": str(item.total_cost) if item.total_cost is not None else None,
                    "pricing_version": item.pricing_version,
                }
                for item in attempts
            ]
            started = await session.scalar(
                select(AnalysisStepRecord.occurred_at)
                .where(
                    AnalysisStepRecord.run_id == run_id,
                    AnalysisStepRecord.stage == request.role.value,
                    AnalysisStepRecord.status == "RUNNING",
                )
                .order_by(AnalysisStepRecord.sequence.desc())
                .limit(1)
            )
            run = AgentRunRecord(
                agent_role=request.role.value,
                model_provider=last.provider if last else "unavailable",
                model_name=last.model_name if last else "unavailable",
                prompt_version=PROMPT_VERSION,
                input_snapshot_hash=request.input_snapshot_hash,
                started_at=started or datetime.now(UTC),
                ended_at=datetime.now(UTC),
                status="SUCCEEDED" if payload else "INSUFFICIENT_DATA",
                token_usage_json={
                    "input": sum(item.input_tokens for item in attempts),
                    "output": sum(item.output_tokens for item in attempts),
                    "cost": str(
                        sum((item.total_cost or Decimal(0) for item in attempts), Decimal(0))
                    )
                    if attempts
                    else None,
                },
                error_code=failure,
                **{
                    **audit(run_id),
                    "metadata_json": {
                        "schema_kind": schema_kind,
                        "prompt_hash": request.prompt_bundle_hash,
                        "attempts": telemetry,
                        "cost_unconfirmed": failure == "GATEWAY_FAILURE",
                    },
                },
            )
            session.add(run)
            await session.flush()
            output: dict[str, object] = {
                "agent_run_id": str(run.id),
                "schema_kind": schema_kind,
                "validated_output": payload,
                "failure": failure,
                "attempts": telemetry,
            }
            session.add(
                AnalysisRoleOutputRecord(
                    run_id=run_id,
                    role=request.role.value,
                    round_number=0,
                    schema_kind=schema_kind,
                    agent_run_id=run.id,
                    payload_json=output,
                    content_hash=fingerprint(output),
                    **audit(run_id),
                )
            )
            await append_step(
                session,
                record,
                stage=request.role.value,
                status="COMPLETED" if payload else "FAILED",
                payload=output,
                reason_code=failure,
            )
