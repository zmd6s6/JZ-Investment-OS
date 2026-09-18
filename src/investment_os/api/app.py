"""Bootstrap API with liveness and real infrastructure readiness endpoints."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response, status

from investment_os.application.health import AsyncClosable, ReadinessProbe
from investment_os.application.research import ResearchArtifactDTO
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.database import DatabaseReadinessProbe
from investment_os.infrastructure.evidence_ingestion import SqlAlchemyEvidenceIngestor
from investment_os.infrastructure.settings import get_settings

from .schemas import (
    LivenessResponse,
    ReadinessResponse,
    ResearchIngestRequest,
    ResearchIngestResponse,
)


def create_app(
    readiness_probe: ReadinessProbe | None = None,
    evidence_ingestor: SqlAlchemyEvidenceIngestor | None = None,
) -> FastAPI:
    """Build an application, allowing tests to inject a deterministic probe."""

    selected_probe = readiness_probe or DatabaseReadinessProbe(get_settings().database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if isinstance(selected_probe, AsyncClosable):
            await selected_probe.close()

    application = FastAPI(
        title="Personal AI Investment OS",
        version="0.1.0",
        description="PR-00 infrastructure health API; no investment behavior is implemented.",
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

    return application


app = create_app()
