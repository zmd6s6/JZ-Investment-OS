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
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from investment_os.application.agent_runtime import AgentRuntime
from investment_os.application.analysis_jobs import AnalysisJobService
from investment_os.application.analysis_market import AnalysisMarketConfiguration
from investment_os.application.analysis_models import AnalysisModelConfiguration
from investment_os.application.analysis_orchestrator import default_registry
from investment_os.application.analysis_product import ProductAnalysisService
from investment_os.application.analysis_run import AnalysisRunService
from investment_os.application.committee_runtime import CommitteeRuntime
from investment_os.application.llm_gateway import LLMGatewayResponse
from investment_os.application.market_data import InMemoryMarketDataAdapter, MarketQuote
from investment_os.application.portfolio_book import PortfolioBookService
from investment_os.application.provider_settings import ProviderSettingsService
from investment_os.domain.enums import ThesisState
from investment_os.domain.thesis import (
    EvidenceBackedClaim,
    PillarStatus,
    ThesisChangeReason,
    ThesisContent,
    ThesisPillar,
)
from investment_os.infrastructure.analysis_execution_context import SqlAnalysisExecutionContexts
from investment_os.infrastructure.analysis_inputs import SqlAlchemyAnalysisInputs
from investment_os.infrastructure.analysis_jobs import SqlAlchemyAnalysisJobs
from investment_os.infrastructure.analysis_market import PlannedMarketDataFactory
from investment_os.infrastructure.analysis_market_audit import SqlAnalysisMarketAudit
from investment_os.infrastructure.analysis_run_store import SessionAnalysisRunPort
from investment_os.infrastructure.analysis_strategy import SqlAnalysisStrategies
from investment_os.infrastructure.catalog_portfolio import (
    SessionCatalogPort,
    SessionPortfolioBookPort,
)
from investment_os.infrastructure.database import create_database_engine, create_session_factory
from investment_os.infrastructure.persistence.models import (
    EvidenceRecord,
    InvestmentThesisRecord,
    ThesisVersionRecord,
)
from investment_os.infrastructure.provider_settings import SqlAlchemyProviderSettingsStore
from investment_os.infrastructure.secrets import EncryptedFileSecretStore
from investment_os.infrastructure.settings import Settings
from investment_os.infrastructure.thesis_engine import SqlAlchemyThesisWriter

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
        self.profile_ids = []
        self.thesis_version_ids = []

    async def complete(self, request):
        self.calls += 1
        self.profile_ids.append(
            str(request.model_binding.profile.profile_id) if request.model_binding else None
        )
        value = json.loads(request.input_payload_json)
        version = value.get("thesis", {}).get("version")
        self.thesis_version_ids.append(version["id"] if version else None)
        await self.release.wait()
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
settings = Settings()
secret_store = EncryptedFileSecretStore(settings.secret_store_path, settings.secret_store_key)
profiles = ProviderSettingsService(SqlAlchemyProviderSettingsStore(sessions), secret_store)
market_calls = []
market_release = asyncio.Event()
market_release.set()


class SyntheticQuotes:
    """Only the isolated fixture registry uses this source; never calls a real provider."""

    name = "SYNTHETIC_FIXTURE_ONLY"

    def __init__(self, profile):
        self.profile = profile

    async def get_quotes(self, requests, *, as_of):
        market_calls.append(str(self.profile.id))
        if self.profile.name.startswith("合成阻塞行情"):
            await market_release.wait()
        if self.profile.name.startswith("合成空行情"):
            return {}
        return {
            q.instrument_id: MarketQuote(
                q.instrument_id,
                Decimal("12.3456789"),
                q.expected_currency,
                as_of,
                self.name,
                volatility=Decimal("0.20"),
            )
            for q in requests
        }


market_factory = PlannedMarketDataFactory(
    profiles,
    secret_store,
    {"TUSHARE_MARKET": lambda profile, credential, client: SyntheticQuotes(profile)},
)
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
    model_configuration=AnalysisModelConfiguration(profiles),
    market_configuration=AnalysisMarketConfiguration(profiles, market_factory.supported_types),
    market_factory=market_factory,
    market_audit=SqlAnalysisMarketAudit(sessions),
    strategy_catalog=SqlAnalysisStrategies(sessions),
    execution_context_store=SqlAnalysisExecutionContexts(sessions),
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
        existing = next(
            (p for p in await profiles.list_model_profiles() if p.name == "合成后台模型"), None
        )
        synthetic = await profiles.save_model_profile(
            profile_id=existing.id if existing else None,
            name="合成后台模型",
            provider_type="OPENAI_COMPATIBLE",
            base_url="https://synthetic.example.test/v1",
            model_name="fixture-only",
            timeout_seconds=30,
            max_tokens=2048,
            enabled=True,
            credential="synthetic-fixture-only",
            pricing_version="synthetic-v1",
            pricing_currency="USD",
            input_token_price=Decimal("0.000001"),
            output_token_price=Decimal("0.000002"),
        )
        await profiles.save_role_assignment(role="DEFAULT", model_provider_profile_id=synthetic.id)
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
    gateway.profile_ids = []
    gateway.thesis_version_ids = []
    market_calls.clear()
    market_release.set()
    return {"mode": "synthetic", "held": True}


@app.post("/api/v1/test-only/analysis/release")
async def release():
    gateway.release.set()
    return {"mode": "synthetic"}


@app.post("/api/v1/test-only/analysis/market-hold")
async def hold_market():
    market_release.clear()
    return {"mode": "synthetic"}


@app.post("/api/v1/test-only/analysis/market-release")
async def release_market():
    market_release.set()
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
    return {
        "mode": "synthetic",
        "calls": gateway.calls,
        "profile_ids": gateway.profile_ids,
        "thesis_version_ids": gateway.thesis_version_ids,
        "market_profile_ids": market_calls,
    }


@app.post("/api/v1/test-only/analysis/thesis")
async def seed_thesis(instrument_id: UUID):
    """Synthetic browser setup only; the production app never imports this fixture."""
    now = datetime.now(UTC)
    async with sessions() as session:
        evidence_id = await session.scalar(
            select(EvidenceRecord.id)
            .where(
                EvidenceRecord.instrument_id == instrument_id,
                EvidenceRecord.available_at <= now,
            )
            .order_by(EvidenceRecord.id)
            .limit(1)
        )
        previous = await session.scalar(
            select(ThesisVersionRecord.version)
            .join(
                InvestmentThesisRecord,
                InvestmentThesisRecord.id == ThesisVersionRecord.thesis_id,
            )
            .where(InvestmentThesisRecord.instrument_id == instrument_id)
            .order_by(ThesisVersionRecord.version.desc())
            .limit(1)
        )
    if evidence_id is None:
        raise ValueError("synthetic evidence required")
    result = await SqlAlchemyThesisWriter(sessions, now=lambda: now).write(
        instrument_id=instrument_id,
        as_of=now,
        content=ThesisContent(
            state=ThesisState.VALID,
            long_term_summary=f"合成固定逻辑版本 {(previous or 0) + 1}",
            pillars=(
                ThesisPillar(
                    "synthetic",
                    EvidenceBackedClaim("合成历史主张", (evidence_id,)),
                    PillarStatus.VALID,
                ),
            ),
            catalysts=(),
            risks=(),
            invalidation_conditions=(),
            monitoring_conditions=("核对下一份合成资料",),
            change_reason=ThesisChangeReason.NEW_EVIDENCE,
        ),
    )
    return {"id": str(result.thesis_version_id), "version": result.version}
