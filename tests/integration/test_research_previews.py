import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from investment_os.api.app import create_app
from investment_os.application.analysis_product import ProductAnalysisService, StartAnalysisInput
from investment_os.application.analysis_run import AnalysisRunService
from investment_os.application.errors import ApplicationError
from investment_os.application.instrument_catalog import InstrumentCatalogService
from investment_os.application.portfolio_book import PortfolioBookService
from investment_os.application.provider_settings import ProviderSettingsService
from investment_os.application.research_preview import ResearchPreviewError, ResearchPreviewService
from investment_os.application.research_runtime import (
    DataProviderRuntimeRegistry,
    ResearchProviderRuntime,
)
from investment_os.domain.instrument import InstrumentIdentity
from investment_os.infrastructure.analysis_inputs import SqlAlchemyAnalysisInputs
from investment_os.infrastructure.analysis_run_store import SessionAnalysisRunPort
from investment_os.infrastructure.bocha.adapter import BochaWebSearchProvider
from investment_os.infrastructure.catalog_portfolio import (
    SessionCatalogPort,
    SessionPortfolioBookPort,
)
from investment_os.infrastructure.evidence_ingestion import SqlAlchemyEvidenceIngestor
from investment_os.infrastructure.persistence.models import (
    AnalysisRunRecord,
    AuditLogRecord,
    DataProviderProfileRecord,
    EventLogRecord,
    EvidenceRecord,
    OutboxEventRecord,
    ResearchArtifactRecord,
    ResearchConfirmationRecord,
    ResearchPreviewRecord,
)
from investment_os.infrastructure.provider_settings import SqlAlchemyProviderSettingsStore
from investment_os.infrastructure.research_preview import SqlAlchemyResearchPreviews

NOW = datetime(2026, 10, 15, 8, tzinfo=UTC)


class Secrets:
    async def put(self, identity: UUID, value: str) -> None:
        pass

    async def get(self, identity: UUID) -> str:
        return "synthetic-preview-credential"

    async def delete(self, identity: UUID) -> None:
        pass


async def setup(database_engine: AsyncEngine):
    factory = async_sessionmaker(database_engine, expire_on_commit=False)
    settings = ProviderSettingsService(SqlAlchemyProviderSettingsStore(factory), Secrets())
    profile = await settings.save_data_profile(
        profile_id=None,
        name="合成预览来源",
        provider_type="BOCHA_WEB_SEARCH",
        base_url="https://synthetic.example.test/v1",
        timeout_seconds=10,
        enabled=True,
        credential="synthetic",
    )
    catalog = InstrumentCatalogService(SessionCatalogPort(factory))
    target = await catalog.register(
        InstrumentIdentity("SSE", "600081", "合成预览标的", "EQUITY", "CNY", "")
    )
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "webPages": {
                        "value": [
                            {
                                "name": f"候选 {index}",
                                "url": f"https://issuer.example.test/preview/{index}",
                                "summary": "不可信合成材料",
                                "datePublished": "2026-10-01T00:00:00Z",
                            }
                            for index in range(2)
                        ]
                    }
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    runtime = ResearchProviderRuntime(
        provider_settings=settings,
        secret_store=Secrets(),
        registry=DataProviderRuntimeRegistry(
            {
                "BOCHA_WEB_SEARCH": lambda profile, credential: BochaWebSearchProvider(
                    profile=profile, credential=credential, client=client
                )
            }
        ),
    )
    clock = [NOW]
    service = ResearchPreviewService(
        SqlAlchemyResearchPreviews(factory), runtime, now=lambda: clock[0]
    )
    return factory, catalog, profile, target, service, clock, calls, client


async def preview(service, profile, target, request_id=None):
    return await service.preview(
        request_id=request_id or uuid4(),
        profile_id=profile.id,
        instrument_id=target.instrument_id,
        query="合成公开查询",
        max_results=2,
    )


async def count(factory, model):
    async with factory() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def test_preview_has_no_evidence_and_concurrent_replay_does_not_requery(database_engine):
    factory, _, profile, target, service, clock, calls, client = await setup(database_engine)
    try:
        request_id = uuid4()
        first, second = await asyncio.gather(
            *[preview(service, profile, target, request_id) for _ in range(2)]
        )
        assert first == second
        assert len(calls) == 1
        assert await count(factory, EvidenceRecord) == 0
        assert await count(factory, ResearchArtifactRecord) == 0
        assert await count(factory, ResearchPreviewRecord) == 1
        with pytest.raises(ResearchPreviewError, match="request_conflict"):
            await service.preview(
                request_id=request_id,
                profile_id=profile.id,
                instrument_id=target.instrument_id,
                query="不同查询",
                max_results=2,
            )
        selected = (first.candidates[0].candidate_id,)
        a, b = await asyncio.gather(
            *[service.confirm(first.preview_id, target.instrument_id, selected) for _ in range(2)]
        )
        assert a == b
        assert await count(factory, EvidenceRecord) == 1
        assert await count(factory, ResearchConfirmationRecord) == 1
        assert (await service.get(first.preview_id)).confirmation == a
        with pytest.raises(ResearchPreviewError, match="selection_conflict"):
            await service.confirm(
                first.preview_id, target.instrument_id, (first.candidates[1].candidate_id,)
            )
        clock[0] += timedelta(days=1)
        assert await service.confirm(first.preview_id, target.instrument_id, selected) == a
        async with factory() as session:
            for event_type in ("RESEARCH_PREVIEW_CREATED", "RESEARCH_PREVIEW_CONFIRMED"):
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(EventLogRecord)
                        .where(EventLogRecord.event_type == event_type)
                    )
                    == 1
                )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(AuditLogRecord)
                    .where(AuditLogRecord.entity_type == "research_collection")
                )
                == 2
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(OutboxEventRecord)
                    .where(OutboxEventRecord.topic == "research.collection")
                )
                == 2
            )
    finally:
        await client.aclose()


@pytest.mark.parametrize("status", ["SUCCEEDED", "FAILED"])
async def test_selected_inputs_are_frozen_before_models_and_cannot_be_rewritten(
    database_engine, monkeypatch, status
):
    factory, _, profile, target, service, _, _, client = await setup(database_engine)
    try:
        draft = await preview(service, profile, target)
        commits = await service.confirm(
            draft.preview_id,
            target.instrument_id,
            tuple(item.candidate_id for item in draft.candidates),
        )
        chosen = commits[0].evidence_id
        catalog_port = SessionCatalogPort(factory)
        portfolios = PortfolioBookService(SessionPortfolioBookPort(factory), catalog_port)
        portfolio = await portfolios.create_portfolio(
            name="合成冻结组合", base_currency="CNY", cash_balance=Decimal("10000")
        )
        runs = AnalysisRunService(SessionAnalysisRunPort(factory))
        observed = []

        async def execute(request, **kwargs):
            active = await runs.list_for_portfolio(portfolio_id=portfolio.portfolio_id)
            assert len(active) == 1 and active[0].status == "RUNNING"
            snapshot = active[0].payload["input_snapshot"]
            assert [item["evidence_id"] for item in snapshot["evidence"]] == [str(chosen)]
            assert [item.evidence_id for item in request.evidence] == [chosen]
            assert Decimal(snapshot["portfolio"]["cash_balance"]) == Decimal("10000")
            observed.append(snapshot)
            await portfolios.set_cash_balance(portfolio.portfolio_id, Decimal("20000"))
            return SimpleNamespace(
                status=status,
                payload=SimpleNamespace(to_dict=lambda: {"stage": "DONE"})
                if status == "SUCCEEDED"
                else None,
                failure_code="SYNTHETIC_FAILURE",
                failure_detail="合成失败",
            )

        monkeypatch.setattr("investment_os.application.analysis_product.execute_analysis", execute)
        product = ProductAnalysisService(
            inputs=SqlAlchemyAnalysisInputs(factory),
            portfolios=portfolios,
            analysis_runs=runs,
            committee=None,
            market_data=None,
            catalog=catalog_port,
        )
        run = await product.start(
            StartAnalysisInput(
                target.instrument_id,
                portfolio.portfolio_id,
                "RESEARCH",
                NOW,
                (chosen,),
            )
        )
        assert run.status == status
        assert run.payload["input_snapshot"] == observed[0]
        assert (await portfolios.get_portfolio(portfolio.portfolio_id)).cash_balance == Decimal(
            "20000"
        )
        retained = await runs.finish(run.id, status=status, payload={"stage": "REFRESH"})
        assert retained.payload["input_snapshot"] == observed[0]
        with pytest.raises(ValueError, match="immutable"):
            await runs.finish(run.id, status=status, payload={"input_snapshot": {}})
        for statement in (
            update(AnalysisRunRecord).where(AnalysisRunRecord.id == run.id).values(payload_json={}),
            text("DELETE FROM analysis_run WHERE id = :id").bindparams(id=run.id),
        ):
            with pytest.raises(DBAPIError, match="immutable"):
                async with database_engine.begin() as connection:
                    await connection.execute(statement)
        async with factory() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(EventLogRecord)
                    .where(EventLogRecord.event_type == "ANALYSIS_INPUT_FROZEN")
                )
                == 1
            )
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "selection", ["empty", "duplicate", "missing", "cross_target", "expired", "future"]
)
async def test_explicit_analysis_selection_rejects_invalid_inputs(database_engine, selection):
    factory, _, profile, target, service, _, _, client = await setup(database_engine)
    try:
        draft = await preview(service, profile, target)
        chosen = (
            await service.confirm(
                draft.preview_id,
                target.instrument_id,
                (draft.candidates[0].candidate_id,),
            )
        )[0].evidence_id
        identity, as_of, ids = target.instrument_id, NOW, (chosen,)
        if selection == "empty":
            ids = ()
        elif selection == "duplicate":
            ids = (chosen, chosen)
        elif selection == "missing":
            ids = (chosen, uuid4())
        elif selection == "cross_target":
            identity = uuid4()
        elif selection == "expired":
            as_of = NOW + timedelta(days=366)
        elif selection == "future":
            as_of = NOW - timedelta(seconds=1)
        with pytest.raises(ApplicationError) as failure:
            await SqlAlchemyAnalysisInputs(factory).evidence(
                identity, as_of=as_of, evidence_ids=ids
            )
        assert failure.value.code.value == "ANALYSIS_EVIDENCE_SELECTION_INVALID"
        assert await count(factory, AnalysisRunRecord) == 0
    finally:
        await client.aclose()


async def test_confirm_is_all_or_nothing_and_rejects_forged_selection(database_engine, monkeypatch):
    factory, _, profile, target, service, _, _, client = await setup(database_engine)
    try:
        draft = await preview(service, profile, target)
        with pytest.raises(ResearchPreviewError, match="instrument_mismatch"):
            await service.confirm(draft.preview_id, uuid4(), (draft.candidates[0].candidate_id,))
        with pytest.raises(ResearchPreviewError, match="selection_invalid"):
            await service.confirm(draft.preview_id, target.instrument_id, (uuid4(),))
        original = SqlAlchemyEvidenceIngestor.persist_in_uow
        writes = 0

        async def fail_second(*args):
            nonlocal writes
            writes += 1
            result = await original(*args)
            if writes == 2:
                raise RuntimeError("synthetic transaction failure")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(SqlAlchemyEvidenceIngestor, "persist_in_uow", staticmethod(fail_second))
            with pytest.raises(RuntimeError, match="synthetic transaction failure"):
                await service.confirm(
                    draft.preview_id,
                    target.instrument_id,
                    tuple(item.candidate_id for item in draft.candidates),
                )
        for model in (EvidenceRecord, ResearchArtifactRecord, ResearchConfirmationRecord):
            assert await count(factory, model) == 0
        assert (
            len(
                await service.confirm(
                    draft.preview_id,
                    target.instrument_id,
                    tuple(item.candidate_id for item in draft.candidates),
                )
            )
            == 2
        )
    finally:
        await client.aclose()


@pytest.mark.parametrize("failure", ["expired", "disabled", "future", "expired_candidate"])
async def test_confirmation_fails_closed_for_time_and_source_boundaries(database_engine, failure):
    factory, _, profile, target, service, clock, _, client = await setup(database_engine)
    try:
        if failure in {"future", "expired_candidate"}:
            original_fetch = service._runtime.fetch

            async def changed_fetch(**kwargs):
                artifacts = await original_fetch(**kwargs)
                from investment_os.domain.values import UtcTimestamp

                if failure == "future":
                    return [
                        replace(item, available_at=UtcTimestamp(NOW + timedelta(hours=1)))
                        for item in artifacts
                    ]
                return [replace(item, expires_at=UtcTimestamp(NOW)) for item in artifacts]

            service._runtime.fetch = changed_fetch
        draft = await preview(service, profile, target)
        if failure == "expired":
            clock[0] = draft.expires_at
        if failure == "disabled":
            async with factory() as session:
                await session.execute(
                    update(DataProviderProfileRecord)
                    .where(DataProviderProfileRecord.id == profile.id)
                    .values(enabled=False)
                )
                await session.commit()
        expected = (
            "expired"
            if failure == "expired"
            else "source_disabled"
            if failure == "disabled"
            else "candidate_unavailable"
        )
        with pytest.raises(ResearchPreviewError, match=expected):
            await service.confirm(
                draft.preview_id, target.instrument_id, (draft.candidates[0].candidate_id,)
            )
        assert await count(factory, EvidenceRecord) == 0
    finally:
        await client.aclose()


async def test_preview_api_restores_draft_and_never_accepts_client_content(database_engine):
    factory, catalog, profile, target, service, _, calls, client = await setup(database_engine)
    app = create_app(
        instrument_catalog_service=catalog,
        research_preview_service=service,
        write_api_token="synthetic-preview-api",
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as browser:
            headers = {"Authorization": "Bearer synthetic-preview-api"}
            request_id = uuid4()
            response = await browser.post(
                f"/api/v1/research/providers/{profile.id}/preview",
                headers=headers,
                json={
                    "request_id": str(request_id),
                    "instrument_id": str(target.instrument_id),
                    "query": "合成公开查询",
                    "max_results": 2,
                },
            )
            assert response.status_code == 200
            draft = response.json()
            assert "synthetic-preview-credential" not in response.text
            restored = (await browser.get(f"/api/v1/research/previews/{request_id}")).json()
            assert datetime.fromisoformat(restored["as_of"].replace("Z", "+00:00")).tzinfo
            assert {key: value for key, value in restored.items() if key != "as_of"} == {
                key: value for key, value in draft.items() if key != "as_of"
            }
            forged = await browser.post(
                f"/api/v1/research/previews/{request_id}/confirm",
                headers=headers,
                json={
                    "instrument_id": str(target.instrument_id),
                    "candidate_ids": [draft["candidates"][0]["candidate_id"]],
                    "payload": {"source_tier": "PRIMARY"},
                },
            )
            assert forged.status_code == 422
            assert await count(factory, EvidenceRecord) == 0
            confirmed = await browser.post(
                f"/api/v1/research/previews/{request_id}/confirm",
                headers=headers,
                json={
                    "instrument_id": str(target.instrument_id),
                    "candidate_ids": [draft["candidates"][0]["candidate_id"]],
                },
            )
            assert confirmed.status_code == 200
            assert len(calls) == 1
        async with factory() as session:
            assert (await session.scalars(select(EvidenceRecord))).one().source_tier == "OTHER"
        for table in ("research_preview", "research_confirmation"):
            with pytest.raises(DBAPIError, match="append-only"):
                async with database_engine.begin() as connection:
                    await connection.execute(text(f"DELETE FROM {table}"))
        await database_engine.dispose()
        with pytest.raises(RuntimeError, match="禁止删除"):
            await asyncio.to_thread(
                command.downgrade, Config("alembic.ini"), "20261010_0015_analysis_run"
            )
    finally:
        await client.aclose()
