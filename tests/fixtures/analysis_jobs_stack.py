"""Explicitly isolated browser fixture: real queue/worker, synthetic models only.

Run only with INVESTMENT_OS_E2E_ANALYSIS=synthetic and the named disposable DB.
Test-control routes are never imported by the production composition root.
"""

import asyncio
import base64
import json
import os
import secrets
from contextlib import asynccontextmanager, suppress

from investment_os.application.agent_runtime import AgentRuntime
from investment_os.application.analysis_jobs import AnalysisJobService
from investment_os.application.analysis_orchestrator import default_registry
from investment_os.application.analysis_product import ProductAnalysisService
from investment_os.application.analysis_run import AnalysisRunService
from investment_os.application.committee_runtime import CommitteeRuntime
from investment_os.application.llm_gateway import LLMGatewayResponse
from investment_os.application.market_data import InMemoryMarketDataAdapter
from investment_os.application.portfolio_book import PortfolioBookService
from investment_os.infrastructure.analysis_inputs import SqlAlchemyAnalysisInputs
from investment_os.infrastructure.analysis_jobs import SqlAlchemyAnalysisJobs
from investment_os.infrastructure.analysis_run_store import SessionAnalysisRunPort
from investment_os.infrastructure.catalog_portfolio import (
    SessionCatalogPort,
    SessionPortfolioBookPort,
)
from investment_os.infrastructure.database import create_database_engine, create_session_factory

database = os.environ.get("INVESTMENT_OS_DATABASE_URL", "")
if os.environ.get("INVESTMENT_OS_E2E_ANALYSIS") != "synthetic" or not database.endswith(
    "/investment_os_p6_jobs_e2e_20261016"
):
    raise RuntimeError("合成分析夹具只允许显式命名隔离数据库")
os.environ.setdefault(
    "INVESTMENT_OS_SECRET_STORE_KEY", base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
)


def create_fixture_app():
    from investment_os.api.bootstrap import create_production_app

    return create_production_app()


class ControlledGateway:
    def __init__(self):
        self.release = asyncio.Event()
        self.release.set()
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        await self.release.wait()
        value = json.loads(request.input_payload_json)
        return LLMGatewayResponse(
            provider="SYNTHETIC",
            model_name="fixture-only",
            latency_ms=1,
            input_tokens=10,
            output_tokens=20,
            raw_output=json.dumps(
                {
                    "schema_version": "1.0",
                    "agent_role": request.role.value,
                    "instrument_id": value["instrument"]["instrument_id"],
                    "as_of": value["as_of"],
                    "stance": "NEUTRAL",
                    "confidence": "0.6",
                    "time_horizon": "DAYS",
                    "observations": [
                        {
                            "claim": "合成测试事实",
                            "evidence_ids": value["evidence_ids"][:1],
                            "materiality": "LOW",
                        }
                    ],
                    "thesis_impacts": [],
                    "assumptions": [],
                    "risks": [],
                    "invalidation_conditions": [],
                    "unknowns": ["仅合成验收"],
                    "requested_followups": [],
                }
            ),
        )


engine = create_database_engine(database)
sessions = create_session_factory(engine)
gateway = ControlledGateway()
catalog = SessionCatalogPort(sessions)
product = ProductAnalysisService(
    inputs=SqlAlchemyAnalysisInputs(sessions),
    portfolios=PortfolioBookService(SessionPortfolioBookPort(sessions), catalog),
    analysis_runs=AnalysisRunService(SessionAnalysisRunPort(sessions)),
    committee=CommitteeRuntime(
        agent_runtime=AgentRuntime(registry=default_registry(), gateway=gateway)
    ),
    market_data=InMemoryMarketDataAdapter(),
    catalog=catalog,
)
jobs = AnalysisJobService(SqlAlchemyAnalysisJobs(engine, sessions), product)
app = create_fixture_app()
original_lifespan = app.router.lifespan_context
worker = None


async def worker_loop():
    while True:
        if not await jobs.run_once():
            await asyncio.sleep(0.1)


@asynccontextmanager
async def lifespan(application):
    global worker
    async with original_lifespan(application):
        worker = asyncio.create_task(worker_loop())
        try:
            yield
        finally:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
            await engine.dispose()


app.router.lifespan_context = lifespan


@app.post("/api/v1/test-only/analysis/hold")
async def hold():
    gateway.release.clear()
    gateway.calls = 0
    return {"mode": "synthetic", "held": True}


@app.post("/api/v1/test-only/analysis/release")
async def release():
    gateway.release.set()
    return {"mode": "synthetic"}


@app.post("/api/v1/test-only/analysis/restart")
async def restart():
    global worker
    worker.cancel()
    with suppress(asyncio.CancelledError):
        await worker
    worker = asyncio.create_task(worker_loop())
    return {"mode": "synthetic"}


@app.get("/api/v1/test-only/analysis/stats")
async def stats():
    return {"mode": "synthetic", "calls": gateway.calls}
