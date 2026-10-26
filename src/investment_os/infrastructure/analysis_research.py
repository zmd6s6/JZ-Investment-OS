"""Publish real research tables in the caller's terminal-state transaction."""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.analysis_research import CompletedResearch, ResearchRecordView
from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.research_preview import content_hash
from investment_os.domain.errors import DomainError
from investment_os.domain.risk import RiskAssessment, RiskFlag, RiskFlagKind, RiskSeverity
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.analysis_execution_context import read_execution_context
from investment_os.infrastructure.persistence.agent_observability import (
    agent_opinion_record_from_result,
    agent_run_record_from_result,
    committee_message_records_from_result,
    committee_session_record_from_result,
    conflict_records_from_result,
)
from investment_os.infrastructure.persistence.models import (
    AgentOpinionEvidenceRecord,
    AgentOpinionRecord,
    AgentRunRecord,
    AnalysisRunRecord,
    CommitteeSessionRecord,
    EventLogRecord,
    EvidenceRecord,
    RiskAssessmentEvidenceRecord,
    RiskAssessmentRecord,
)
from investment_os.infrastructure.research_preview import append_event

EVENT = "ANALYSIS_RESEARCH_RECORDED"


def invalid() -> ApplicationError:
    return ApplicationError(
        ApplicationErrorCode.ANALYSIS_RESEARCH_INVALID,
        "stored research provenance cannot be verified",
    )


async def publish_research(
    session: AsyncSession,
    run: AnalysisRunRecord,
    research: CompletedResearch,
    valuation: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Caller owns the locked run and transaction; no independent commit here."""
    snapshot = run.payload_json["input_snapshot"]
    execution = await read_execution_context(session, run)
    runtime_hash = (
        execution.receipt.runtime_input_hash if execution.receipt else snapshot["input_hash"]
    )
    if execution.valuation is not None and (
        valuation is None
        or any(
            valuation.get(key) != value
            for key, value in execution.valuation.model_dump(mode="json").items()
        )
    ):
        raise invalid()
    if (
        research.context.input_snapshot_hash != runtime_hash
        or research.context.instrument_id != run.instrument_id
        or research.context.as_of.value != run.as_of
        or research.assessment.as_of.value != run.as_of
    ):
        raise invalid()
    existing = await session.scalar(
        select(EventLogRecord).where(
            EventLogRecord.aggregate_id == run.id,
            EventLogRecord.event_type == EVENT,
            EventLogRecord.aggregate_type == "analysis_research",
        )
    )
    if existing is not None:
        raise invalid()
    expected = {UUID(e["evidence_id"]): e["content_hash"] for e in snapshot["evidence"]}
    rows = list(
        await session.scalars(select(EvidenceRecord).where(EvidenceRecord.id.in_(expected)))
    )
    if (
        set(expected) != research.context.visible_evidence_ids
        or len(rows) != len(expected)
        or any(
            e.content_hash != expected[e.id]
            or e.instrument_id not in (None, run.instrument_id)
            or e.available_at > run.as_of
            or e.ingested_at > run.as_of
            for e in rows
        )
    ):
        raise invalid()
    owner = "analysis_worker"
    session_id = uuid4()
    committee = committee_session_record_from_result(
        session_id=session_id,
        result=research.committee,
        context=research.context,
        started_at=research.started_at,
        completed_at=research.completed_at,
        created_by=owner,
        correlation_id=run.id,
    )
    session.add(committee)
    await session.flush()
    entries = []
    opinion_ids = {}
    bundles = {b.role: b for b in research.prompts}
    pairs = [
        (f"ROUND_{r.plan.number}", r.plan.number, req, res)
        for r in research.committee.rounds
        for req, res in zip(r.requests, r.results, strict=True)
    ] + [
        ("PORTFOLIO", 0, research.portfolio_request, research.portfolio_result),
        ("RISK", 0, research.risk_request, research.risk_result),
    ]
    for stage, number, request, result in pairs:
        if (
            result.started_at is None
            or result.ended_at is None
            or (execution.receipt is not None and execution.receipt.recorded_at > result.started_at)
            or result.ended_at < result.started_at
            or request.input_snapshot_hash != runtime_hash
            or result.opinion.instrument_id != run.instrument_id
            or result.opinion.as_of != research.context.as_of
        ):
            raise invalid()
        refs = {eid for c in result.opinion.observations for eid in c.evidence_ids}
        refs.update(eid for c in result.opinion.risks for eid in c.evidence_ids)
        refs.update(eid for c in result.opinion.thesis_impacts for eid in c.evidence_ids)
        if not refs.issubset(expected):
            raise invalid()
        agent = agent_run_record_from_result(
            request=request,
            prompt_bundle=bundles[request.role],
            result=result,
            started_at=result.started_at,
            ended_at=result.ended_at,
            created_by=owner,
            correlation_id=run.id,
        )
        session.add(agent)
        await session.flush()
        opinion = agent_opinion_record_from_result(
            agent_run_id=agent.id,
            result=result,
            created_by=owner,
            correlation_id=run.id,
        )
        opinion.metadata_json = {
            **opinion.metadata_json,
            "as_of": run.as_of.isoformat(),
            "requested_followups": list(result.opinion.requested_followups),
        }
        session.add(opinion)
        await session.flush()
        session.add_all(
            [
                AgentOpinionEvidenceRecord(agent_opinion_id=opinion.id, evidence_id=eid)
                for eid in refs
            ]
        )
        if number:
            opinion_ids[(number, request.role.value)] = opinion.id
        entries.append(
            {
                "stage": stage,
                "role": request.role.value,
                "agent_run_id": str(agent.id),
                "opinion_id": str(opinion.id),
            }
        )
    session.add_all(
        committee_message_records_from_result(
            session_id=session_id,
            result=research.committee,
            opinion_ids=opinion_ids,
            created_by=owner,
            correlation_id=run.id,
        )
    )
    session.add_all(
        conflict_records_from_result(
            session_id=session_id,
            result=research.committee,
            opinion_ids=opinion_ids,
            created_by=owner,
            correlation_id=run.id,
        )
    )
    assessment = research.assessment
    flags = [
        {
            "code": f.code,
            "kind": f.kind.value,
            "severity": f.severity.value,
            "evidence_ids": [str(e) for e in f.evidence_ids],
            "release_condition": f.release_condition,
        }
        for f in assessment.flags
    ]
    if not set(assessment.evidence_ids).issubset(expected):
        raise invalid()
    risk = RiskAssessmentRecord(
        id=assessment.id,
        session_id=session_id,
        veto=assessment.gate.value == "VETO",
        veto_codes=[f.code for f in assessment.flags if f.kind.value == "HARD"],
        hard_flags_json=[f for f in flags if f["kind"] == "HARD"],
        soft_flags_json=[f for f in flags if f["kind"] == "SOFT"],
        expires_at=assessment.expires_at.value,
        content_hash=assessment.content_hash,
        created_by=owner,
        correlation_id=run.id,
        metadata_json={
            "version": assessment.version,
            "as_of": run.as_of.isoformat(),
            "gate": assessment.gate.value,
        },
    )
    session.add(risk)
    await session.flush()
    session.add_all(
        [
            RiskAssessmentEvidenceRecord(risk_assessment_id=risk.id, evidence_id=eid)
            for eid in set(assessment.evidence_ids)
        ]
    )
    manifest = {
        "schema_version": "1.0",
        "run_id": str(run.id),
        "input_hash": snapshot["input_hash"],
        "runtime_input_hash": runtime_hash,
        "feature_snapshot_id": str(execution.receipt.feature_snapshot_id)
        if execution.receipt
        else None,
        "committee_session_id": str(session_id),
        "risk_assessment_id": str(risk.id),
        "risk_content_hash": risk.content_hash,
        "agents": entries,
        "decision_status": "NOT_REGISTERED",
        "limitations": ["SIZING_CONTEXT_INCOMPLETE", "FORMAL_DECISION_NOT_CREATED"],
    }
    append_event(
        session,
        EVENT,
        run.id,
        content_hash(manifest),
        manifest,
        datetime.now(UTC),
        aggregate="analysis_research",
        topic="analysis.research",
        actor_type="SYSTEM",
        actor_id=owner,
    )
    await session.flush()
    return manifest


class SqlAnalysisResearchReader:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self._sessions = sessions

    async def read(self, run_id: UUID) -> ResearchRecordView:
        try:
            return await self._read(run_id)
        except (KeyError, ValueError, TypeError, DomainError):
            raise invalid() from None

    async def _read(self, run_id: UUID) -> ResearchRecordView:
        async with self._sessions() as session:
            run = await session.get(AnalysisRunRecord, run_id)
            if run is None:
                raise ApplicationError(
                    ApplicationErrorCode.ANALYSIS_RESEARCH_NOT_FOUND, "analysis run not found"
                )
            event = await session.scalar(
                select(EventLogRecord).where(
                    EventLogRecord.aggregate_id == run_id,
                    EventLogRecord.event_type == EVENT,
                    EventLogRecord.aggregate_type == "analysis_research",
                )
            )
            if event is None:
                return ResearchRecordView(
                    run_id=run_id,
                    status="NOT_RECORDED",
                    limitations=("HISTORICAL_RECORDS_NOT_BACKFILLED",),
                )
            manifest = event.payload_json
            execution = await read_execution_context(session, run)
            runtime_hash = (
                execution.receipt.runtime_input_hash
                if execution.receipt
                else manifest["input_hash"]
            )
            if manifest.get(
                "runtime_input_hash", manifest["input_hash"]
            ) != runtime_hash or manifest.get("feature_snapshot_id") != (
                str(execution.receipt.feature_snapshot_id) if execution.receipt else None
            ):
                raise invalid()
            committee = await session.get(
                CommitteeSessionRecord, UUID(manifest["committee_session_id"])
            )
            risk = await session.get(RiskAssessmentRecord, UUID(manifest["risk_assessment_id"]))
            if (
                committee is None
                or risk is None
                or risk.session_id != committee.id
                or committee.correlation_id != run_id
                or risk.correlation_id != run_id
                or committee.input_snapshot_hash != runtime_hash
                or manifest["input_hash"] != run.payload_json["input_snapshot"]["input_hash"]
                or committee.instrument_id != run.instrument_id
                or risk.content_hash != manifest["risk_content_hash"]
            ):
                raise invalid()
            if execution.valuation is not None and (
                run.payload_json.get("context_hash") != runtime_hash
                or any(
                    run.payload_json.get("valuation", {}).get(key) != value
                    for key, value in execution.valuation.model_dump(mode="json").items()
                )
            ):
                raise invalid()
            agents = []
            for entry in manifest["agents"]:
                agent = await session.get(AgentRunRecord, UUID(entry["agent_run_id"]))
                opinion = await session.get(AgentOpinionRecord, UUID(entry["opinion_id"]))
                if (
                    agent is None
                    or opinion is None
                    or opinion.agent_run_id != agent.id
                    or agent.correlation_id != run_id
                    or opinion.correlation_id != run_id
                    or agent.input_snapshot_hash != runtime_hash
                    or agent.agent_role != entry["role"]
                    or opinion.instrument_id != run.instrument_id
                ):
                    raise invalid()
                refs = list(
                    await session.scalars(
                        select(AgentOpinionEvidenceRecord.evidence_id)
                        .where(AgentOpinionEvidenceRecord.agent_opinion_id == opinion.id)
                        .order_by(AgentOpinionEvidenceRecord.evidence_id)
                    )
                )
                declared = {
                    UUID(e)
                    for column in (
                        opinion.observations_json,
                        opinion.thesis_impacts_json,
                        opinion.risks_json,
                    )
                    for c in cast(list[dict[str, Any]], column)
                    for e in c["evidence_ids"]
                }
                if declared != set(refs):
                    raise invalid()
                agents.append(
                    {
                        **entry,
                        "status": agent.status,
                        "error_code": agent.error_code,
                        "model_provider": agent.model_provider,
                        "model_name": agent.model_name,
                        "started_at": agent.started_at.isoformat(),
                        "ended_at": agent.ended_at.isoformat() if agent.ended_at else None,
                        "prompt_version": agent.prompt_version,
                        "prompt_hash": agent.metadata_json["prompt_bundle_hash"],
                        "content_hash": opinion.content_hash,
                        "stance": opinion.stance,
                        "confidence": str(opinion.confidence),
                        "observations": opinion.observations_json,
                        "thesis_impacts": opinion.thesis_impacts_json,
                        "unknowns": opinion.unknowns_json,
                        "evidence_ids": [str(e) for e in refs],
                    }
                )
            refs = list(
                await session.scalars(
                    select(RiskAssessmentEvidenceRecord.evidence_id)
                    .where(RiskAssessmentEvidenceRecord.risk_assessment_id == risk.id)
                    .order_by(RiskAssessmentEvidenceRecord.evidence_id)
                )
            )
            assessment = RiskAssessment(
                id=risk.id,
                version=int(risk.metadata_json["version"]),
                as_of=UtcTimestamp(datetime.fromisoformat(risk.metadata_json["as_of"])),
                expires_at=UtcTimestamp(risk.expires_at),
                flags=tuple(
                    RiskFlag(
                        code=f["code"],
                        kind=RiskFlagKind(f["kind"]),
                        severity=RiskSeverity(f["severity"]),
                        evidence_ids=tuple(UUID(e) for e in f["evidence_ids"]),
                        release_condition=f["release_condition"],
                    )
                    for f in risk.hard_flags_json + risk.soft_flags_json
                ),
            )
            if (
                assessment.content_hash != risk.content_hash
                or assessment.gate.value != risk.metadata_json["gate"]
                or set(assessment.evidence_ids) != set(refs)
                or risk.veto != (assessment.gate.value == "VETO")
            ):
                raise invalid()
            return ResearchRecordView(
                run_id=run_id,
                status="RECORDED",
                committee_session_id=committee.id,
                input_hash=manifest["input_hash"],
                runtime_input_hash=runtime_hash,
                feature_snapshot_id=execution.receipt.feature_snapshot_id
                if execution.receipt
                else None,
                agents=tuple(agents),
                risk={
                    "id": str(risk.id),
                    "gate": risk.metadata_json["gate"],
                    "content_hash": risk.content_hash,
                    "as_of": risk.metadata_json["as_of"],
                    "expires_at": risk.expires_at.isoformat(),
                    "veto": risk.veto,
                    "veto_codes": risk.veto_codes,
                    "hard_flags": risk.hard_flags_json,
                    "soft_flags": risk.soft_flags_json,
                    "evidence_ids": [str(e) for e in refs],
                },
                limitations=tuple(manifest["limitations"]),
            )
