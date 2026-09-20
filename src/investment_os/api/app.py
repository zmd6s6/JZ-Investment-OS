"""Bootstrap API with liveness and real infrastructure readiness endpoints."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime

from investment_os.application.health import AsyncClosable, ReadinessProbe
from investment_os.application.research import ResearchArtifactDTO
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.database import (
    DatabaseReadinessProbe,
    create_database_engine,
    create_session_factory,
)
from investment_os.infrastructure.decision_journal import (
    DecisionJournalRead,
    SqlAlchemyDecisionJournalReader,
)
from investment_os.infrastructure.evidence_ingestion import SqlAlchemyEvidenceIngestor
from investment_os.infrastructure.report_delivery import SqlAlchemyDailyReportReader
from investment_os.infrastructure.scheduler import SqlAlchemyTaskRunReader
from investment_os.infrastructure.settings import get_settings
from investment_os.infrastructure.thesis_engine import SqlAlchemyThesisReader, ThesisVersionRead

from .schemas import (
    DailyReportResponse,
    DecisionJournalResponse,
    LivenessResponse,
    ReadinessResponse,
    ResearchIngestRequest,
    ResearchIngestResponse,
    TaskRunResponse,
    ThesisHistoryResponse,
    ThesisVersionResponse,
)


def _thesis_response(version: ThesisVersionRead) -> ThesisVersionResponse:
    return ThesisVersionResponse.model_validate(
        {
            "instrument_id": version.instrument_id,
            "thesis_id": version.thesis_id,
            "version_id": version.version_id,
            "version": version.version,
            "parent_version_id": version.parent_version_id,
            "state": version.state,
            "long_term_summary": version.summary,
            "pillars": version.pillars,
            "catalysts": version.catalysts,
            "risks": version.risks,
            "invalidation_conditions": version.invalidation_conditions,
            "monitoring_conditions": version.monitoring_conditions,
            "change_reason": version.change_reason,
            "evidence_ids": version.evidence_ids,
            "created_at": version.created_at,
        }
    )


def _decision_journal_response(journal: DecisionJournalRead) -> DecisionJournalResponse:
    return DecisionJournalResponse.model_validate(
        {
            "decision_id": journal.decision_id,
            "instrument_id": journal.instrument_id,
            "portfolio_id": journal.portfolio_id,
            "committee_session_id": journal.committee_session_id,
            "thesis_version_id": journal.thesis_version_id,
            "policy_version_id": journal.policy_version_id,
            "strategy_version_id": journal.strategy_version_id,
            "risk_assessment_id": journal.risk_assessment_id,
            "position_sizing_run_id": journal.position_sizing_run_id,
            "action": journal.action,
            "confidence": journal.confidence,
            "risk_intent": journal.risk_intent,
            "core_action": journal.core_action,
            "tactical_action": journal.tactical_action,
            "state": journal.state,
            "reasons": journal.reasons,
            "risks": journal.risks,
            "watch_conditions": journal.watch_conditions,
            "invalidation_conditions": journal.invalidation_conditions,
            "position_before": journal.position_before,
            "position_after_proposed": journal.position_after_proposed,
            "unknowns": journal.unknowns,
            "dissent": journal.dissent,
            "next_review_at": journal.next_review_at,
            "input_snapshot_hash": journal.input_snapshot_hash,
            "prompt_bundle_version": journal.prompt_bundle_version,
            "formula_version": journal.formula_version,
            "content_hash": journal.content_hash,
            "version": journal.version,
            "evidence_ids": journal.evidence_ids,
            "approvals": [
                {
                    "id": approval.id,
                    "actor_id": approval.actor_id,
                    "action": approval.action,
                    "comment": approval.comment,
                    "expires_at": approval.expires_at,
                    "occurred_at": approval.occurred_at,
                }
                for approval in journal.approvals
            ],
            "executions": [
                {
                    "id": execution.id,
                    "approval_id": execution.approval_id,
                    "execution_mode": execution.execution_mode,
                    "status": execution.status,
                    "requested_quantity": execution.requested_quantity,
                    "filled_quantity": execution.filled_quantity,
                    "avg_price": execution.avg_price,
                    "external_refs": execution.external_refs,
                    "occurred_at": execution.occurred_at,
                }
                for execution in journal.executions
            ],
            "created_at": journal.created_at,
        }
    )


def create_app(
    readiness_probe: ReadinessProbe | None = None,
    evidence_ingestor: SqlAlchemyEvidenceIngestor | None = None,
    thesis_reader: SqlAlchemyThesisReader | None = None,
    decision_journal_reader: SqlAlchemyDecisionJournalReader | None = None,
    task_run_reader: SqlAlchemyTaskRunReader | None = None,
    daily_report_reader: SqlAlchemyDailyReportReader | None = None,
) -> FastAPI:
    """Build an application, allowing tests to inject a deterministic probe."""

    settings = get_settings()
    selected_probe = readiness_probe or DatabaseReadinessProbe(settings.database_url)
    reader_engine = None
    selected_thesis_reader = thesis_reader
    selected_decision_journal_reader = decision_journal_reader
    selected_task_run_reader = task_run_reader
    selected_daily_report_reader = daily_report_reader
    if (
        selected_thesis_reader is None
        or selected_decision_journal_reader is None
        or selected_task_run_reader is None
        or selected_daily_report_reader is None
    ):
        reader_engine = create_database_engine(settings.database_url)
        session_factory = create_session_factory(reader_engine)
        if selected_thesis_reader is None:
            selected_thesis_reader = SqlAlchemyThesisReader(session_factory)
        if selected_decision_journal_reader is None:
            selected_decision_journal_reader = SqlAlchemyDecisionJournalReader(session_factory)
        if selected_task_run_reader is None:
            selected_task_run_reader = SqlAlchemyTaskRunReader(session_factory)
        if selected_daily_report_reader is None:
            selected_daily_report_reader = SqlAlchemyDailyReportReader(session_factory)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if isinstance(selected_probe, AsyncClosable):
            await selected_probe.close()
        if reader_engine is not None:
            await reader_engine.dispose()

    application = FastAPI(
        title="Personal AI Investment OS",
        version="0.1.0",
        description="Evidence-backed research ingestion plus immutable Thesis and Decision Journal "
        "read APIs; no execution.",
        lifespan=lifespan,
    )

    @application.get("/health/live", response_model=LivenessResponse, tags=["health"])
    async def liveness() -> LivenessResponse:
        return LivenessResponse()

    @application.get(
        "/health/ready",
        response_model=ReadinessResponse,
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
        tags=["health"],
    )
    async def readiness(response: Response) -> ReadinessResponse:
        check = await selected_probe.check()
        if not check.ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="ready" if check.ready else "not_ready",
            checks={"database": check.detail},
        )

    @application.post(
        "/api/v1/research/ingest", response_model=ResearchIngestResponse, tags=["research"]
    )
    async def ingest(request: ResearchIngestRequest) -> ResearchIngestResponse:
        if evidence_ingestor is None:
            raise HTTPException(status_code=503, detail="research_ingestion_unavailable")
        artifact = ResearchArtifactDTO(
            provider=request.provider,
            provider_ref=request.provider_ref,
            artifact_type=request.artifact_type,
            source_name=request.source_name,
            source_locator=request.source_locator,
            source_tier=request.source_tier,
            observed_at=UtcTimestamp(request.observed_at),
            effective_at=UtcTimestamp(request.effective_at),
            available_at=UtcTimestamp(request.available_at),
            payload=request.payload,
            source_schema_version=request.source_schema_version,
            instrument_id=request.instrument_id,
            expires_at=UtcTimestamp(request.expires_at) if request.expires_at else None,
            supersedes_id=request.supersedes_id,
        )
        result = await evidence_ingestor.ingest(artifact)
        return ResearchIngestResponse(evidence_id=result.evidence_id, reused=result.reused)

    @application.get(
        "/api/v1/theses/{instrument_id}", response_model=ThesisVersionResponse, tags=["theses"]
    )
    async def read_thesis(
        instrument_id: UUID,
        as_of: AwareDatetime | None = None,
    ) -> ThesisVersionResponse:
        version = (
            await selected_thesis_reader.current_for_instrument(instrument_id)
            if as_of is None
            else await selected_thesis_reader.as_of_for_instrument(instrument_id, as_of=as_of)
        )
        if version is None:
            raise HTTPException(status_code=404, detail="thesis_not_found")
        return _thesis_response(version)

    @application.get(
        "/api/v1/theses/{instrument_id}/versions",
        response_model=ThesisHistoryResponse,
        tags=["theses"],
    )
    async def thesis_history(instrument_id: UUID) -> ThesisHistoryResponse:
        versions = await selected_thesis_reader.history_for_instrument(instrument_id)
        if not versions:
            raise HTTPException(status_code=404, detail="thesis_not_found")
        return ThesisHistoryResponse(
            instrument_id=instrument_id,
            versions=[_thesis_response(version) for version in versions],
        )

    @application.get(
        "/api/v1/decisions/{decision_id}",
        response_model=DecisionJournalResponse,
        tags=["decisions"],
    )
    async def read_decision_journal(decision_id: UUID) -> DecisionJournalResponse:
        journal = await selected_decision_journal_reader.get(decision_id)
        if journal is None:
            raise HTTPException(status_code=404, detail="decision_not_found")
        return _decision_journal_response(journal)

    @application.get("/api/v1/task-runs", response_model=list[TaskRunResponse], tags=["jobs"])
    async def list_task_runs(limit: int = Query(default=50, ge=1, le=100)) -> list[TaskRunResponse]:
        try:
            runs = await selected_task_run_reader.list_recent(limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return [TaskRunResponse.model_validate(run, from_attributes=True) for run in runs]

    @application.get(
        "/api/v1/reports/daily/latest", response_model=DailyReportResponse, tags=["reports"]
    )
    async def latest_daily_report() -> DailyReportResponse:
        try:
            report = await selected_daily_report_reader.latest()
        except ValueError as exc:
            raise HTTPException(status_code=503, detail="daily_report_unavailable") from exc
        if report is None:
            raise HTTPException(status_code=404, detail="daily_report_not_found")
        return DailyReportResponse.model_validate(report, from_attributes=True)

    frontend_dist = Path(__file__).resolve().parents[3] / "web" / "dist"
    if frontend_dist.is_dir():
        application.mount(
            "/assets", StaticFiles(directory=frontend_dist / "assets"), name="web-assets"
        )

        @application.get("/", include_in_schema=False)
        async def personal_ui() -> FileResponse:
            return FileResponse(frontend_dist / "index.html")

    return application


app = create_app()
