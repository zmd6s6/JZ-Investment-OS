"""Bootstrap API with liveness and real infrastructure readiness endpoints."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status

from investment_os.application.health import AsyncClosable, ReadinessProbe
from investment_os.infrastructure.database import DatabaseReadinessProbe
from investment_os.infrastructure.settings import get_settings

from .schemas import LivenessResponse, ReadinessResponse


def create_app(readiness_probe: ReadinessProbe | None = None) -> FastAPI:
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

    return application


app = create_app()
