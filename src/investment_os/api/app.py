"""Bootstrap API with liveness and real infrastructure readiness endpoints."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException, Response, status
from pydantic import AwareDatetime

from investment_os.application.health import AsyncClosable, ReadinessProbe
from investment_os.application.research import ResearchArtifactDTO
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.database import (
    DatabaseReadinessProbe,
    create_database_engine,
    create_session_factory,
)
from investment_os.infrastructure.evidence_ingestion import SqlAlchemyEvidenceIngestor
from investment_os.infrastructure.settings import get_settings
from investment_os.infrastructure.thesis_engine import SqlAlchemyThesisReader, ThesisVersionRead

from .schemas import (
    LivenessResponse,
    ReadinessResponse,
    ResearchIngestRequest,
    ResearchIngestResponse,
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


def create_app(
    readiness_probe: ReadinessProbe | None = None,
    evidence_ingestor: SqlAlchemyEvidenceIngestor | None = None,
    thesis_reader: SqlAlchemyThesisReader | None = None,
) -> FastAPI:
    """Build an application, allowing tests to inject a deterministic probe."""

    settings = get_settings()
    selected_probe = readiness_probe or DatabaseReadinessProbe(settings.database_url)
    reader_engine = None
    selected_thesis_reader = thesis_reader
    if selected_thesis_reader is None:
        reader_engine = create_database_engine(settings.database_url)
        selected_thesis_reader = SqlAlchemyThesisReader(create_session_factory(reader_engine))

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
        description="Evidence-backed research ingestion and immutable Thesis read API; "
        "no execution.",
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

    return application


app = create_app()
