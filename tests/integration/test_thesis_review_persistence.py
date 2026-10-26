"""Saved team observations can be explicitly adopted without changing historical research."""

import asyncio
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from test_analysis_research import configured
from test_thesis_product import command

from investment_os.api.app import create_app
from investment_os.application.errors import ApplicationError
from investment_os.application.research_preview import content_hash
from investment_os.application.thesis_product import ThesisProductService
from investment_os.application.thesis_review import TeamThesisSource
from investment_os.infrastructure.local_access import LocalAccessStore
from investment_os.infrastructure.persistence.models import (
    EventLogRecord,
    InstrumentRecord,
    OutboxEventRecord,
    ThesisVersionRecord,
)
from investment_os.infrastructure.thesis_product import SqlThesisProduct


async def setup(engine):
    sessions, runs, product, _, jobs, inp, gateway = await configured(engine)
    run = await jobs.submit(uuid4(), inp)
    assert await jobs.run_once()
    assert (await runs.get(run.id)).status == "SUCCEEDED"
    service = ThesisProductService(SqlThesisProduct(sessions))
    review = await service.team_review(run.id)
    request = command(inp, state="UNKNOWN").model_copy(
        update={
            "review_source": TeamThesisSource(
                analysis_run_id=run.id, suggestion_ids=tuple(s.id for s in review.suggestions[:2])
            )
        }
    )
    return sessions, runs, product, jobs, inp, gateway, run, service, request


async def test_read_adopt_replay_and_history_keep_actual_source_and_do_not_rerun_models(
    database_engine,
):
    sessions, runs, _, _, inp, gateway, run, service, request = await setup(database_engine)
    before = await runs.get(run.id)
    assert gateway.calls == 8
    assert (await service.workspace(inp.instrument_id)).versions == ()
    results = await asyncio.gather(*(service.save(inp.instrument_id, request) for _ in range(3)))
    assert results[0] == results[1] == results[2]
    saved = results[0]
    workspace = await service.workspace(inp.instrument_id)
    source = workspace.versions[0].review_sources[0]
    assert (
        source.analysis_run_id == run.id
        and source.input_hash == run.payload["input_snapshot"]["input_hash"]
    )
    assert (
        source.suggestion_ids == request.review_source.suggestion_ids
        and len(source.opinion_ids) == 2
    )
    assert workspace.versions[0].content.state.value == "UNKNOWN"
    await service.save(
        inp.instrument_id, command(inp, base=saved.version_id, summary="合成人工下一版")
    )
    assert (
        await service.save(inp.instrument_id, request) == saved
    )  # Replay before source/base validation.
    assert (await runs.get(run.id)).payload == before.payload and gateway.calls == 8
    async with sessions() as session:
        receipt = await session.scalar(
            select(EventLogRecord).where(EventLogRecord.aggregate_id == request.request_id)
        )
        assert receipt.payload_json["review_source"] == source.model_dump(mode="json")
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OutboxEventRecord)
                .where(OutboxEventRecord.event_id == receipt.id)
            )
            == 1
        )


@pytest.mark.parametrize("bad", ["instrument", "selection", "baseline"])
async def test_forged_or_stale_review_source_is_rejected_without_creating_version(
    database_engine, bad
):
    sessions, _, _, _, inp, gateway, _, service, request = await setup(database_engine)
    target = inp.instrument_id
    count = 0
    if bad == "instrument":
        target = uuid4()
        async with sessions() as session, session.begin():
            session.add(
                InstrumentRecord(
                    id=target,
                    symbol="629997",
                    exchange="SSE",
                    name="合成其他标的",
                    asset_type="EQUITY",
                    currency="CNY",
                    status="ACTIVE",
                    created_by="synthetic",
                    correlation_id=uuid4(),
                )
            )
    if bad == "selection":
        request = request.model_copy(
            update={
                "review_source": TeamThesisSource(
                    analysis_run_id=request.review_source.analysis_run_id,
                    suggestion_ids=(f"{uuid4()}:0",),
                )
            }
        )
    if bad == "baseline":
        current = await service.save(target, command(inp))
        count = 1
        request = request.model_copy(update={"expected_version_id": current.version_id})
    with pytest.raises(ApplicationError) as failure:
        await service.save(target, request)
    assert failure.value.code.value == "THESIS_REVIEW_SOURCE_INVALID"
    assert len((await service.workspace(target)).versions) == count and gateway.calls == 8


async def test_review_receipt_failure_rolls_back_version_and_source(database_engine, monkeypatch):
    sessions, _, _, _, inp, _, _, service, request = await setup(database_engine)

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic review receipt failure")

    monkeypatch.setattr("investment_os.infrastructure.thesis_product.append_event", fail)
    with pytest.raises(RuntimeError, match="synthetic review receipt failure"):
        await service.save(inp.instrument_id, request)
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(ThesisVersionRecord)) == 0
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventLogRecord)
                .where(EventLogRecord.event_type == "THESIS_PRODUCT_SAVED")
            )
            == 0
        )


async def test_old_no_source_command_retains_its_request_hash_and_read_route_requires_auth(
    database_engine,
    tmp_path,
):
    sessions, runs, product, jobs, inp, _, run, service, _ = await setup(database_engine)
    request = command(inp)
    await service.save(inp.instrument_id, request)
    original = request.model_dump(mode="json", exclude={"request_id", "review_source"})
    async with sessions() as session:
        receipt = await session.scalar(
            select(EventLogRecord).where(EventLogRecord.aggregate_id == request.request_id)
        )
        assert receipt.payload_json["request_hash"] == content_hash(
            {"instrument_id": str(inp.instrument_id), "command": original}
        )
    app = create_app(
        analysis_product_service=product,
        analysis_run_service=runs,
        analysis_job_service=jobs,
        thesis_product_service=service,
        write_api_token="synthetic-review-auth",
        local_access_store=LocalAccessStore(tmp_path / "review-local-session.sqlite3"),
        local_access_origin="http://127.0.0.1:18104",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:18104"
    ) as client:
        path = f"/api/v1/analysis-runs/{run.id}/thesis-review"
        assert (await client.get(path)).status_code == 401
        response = await client.get(path, headers={"Authorization": "Bearer synthetic-review-auth"})
        assert response.status_code == 200 and len(response.json()["suggestions"]) == 8
    assert len((await service.workspace(inp.instrument_id)).versions) == 1


async def impact_setup(engine):
    sessions, _, _, _, jobs, inp, gateway = await configured(engine, "IMPACT")
    service = ThesisProductService(SqlThesisProduct(sessions))
    first = command(inp)
    pillar = first.content.pillars[0].model_copy(update={"key": "demand"})
    first = first.model_copy(
        update={"content": first.content.model_copy(update={"pillars": (pillar,)})}
    )
    saved = await service.save(inp.instrument_id, first)
    run = await jobs.submit(uuid4(), inp)
    assert await jobs.run_once()
    review = await service.team_review(run.id)
    impact = review.impacts[0]
    assert impact.baseline_status == "MATCHED"
    request = command(inp, base=saved.version_id, summary="人工核对后的合成风险修订")
    request = request.model_copy(
        update={"review_source": TeamThesisSource(analysis_run_id=run.id, impact_ids=(impact.id,))}
    )
    return sessions, inp, gateway, run, service, request, review


async def test_selected_real_impact_source_is_atomic_replayable_and_keeps_original_version(
    database_engine,
):
    sessions, inp, gateway, run, service, request, review = await impact_setup(database_engine)
    before = (await service.workspace(inp.instrument_id)).versions[0]
    saved = await service.save(inp.instrument_id, request)
    assert await service.save(inp.instrument_id, request) == saved
    workspace = await service.workspace(inp.instrument_id)
    assert len(workspace.versions) == 2 and workspace.versions[1] == before
    source = workspace.versions[0].review_sources[0]
    assert source.impact_ids == (review.impacts[0].id,) and source.suggestion_ids == ()
    assert source.opinion_ids == (review.impacts[0].opinion_id,)
    assert gateway.calls == 8 and source.analysis_run_id == run.id
    async with sessions() as session:
        event = await session.scalar(
            select(EventLogRecord).where(EventLogRecord.aggregate_id == request.request_id)
        )
        assert event.payload_json["review_source"] == source.model_dump(mode="json")
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OutboxEventRecord)
                .where(OutboxEventRecord.event_id == event.id)
            )
            == 1
        )


@pytest.mark.parametrize("bad", ["unknown", "positive", "unmatched"])
async def test_impact_selection_rejects_unknown_or_ineligible_source_without_writing(
    database_engine, monkeypatch, bad
):
    _, inp, gateway, _, service, request, review = await impact_setup(database_engine)
    if bad == "unknown":
        request = request.model_copy(
            update={
                "review_source": request.review_source.model_copy(
                    update={"impact_ids": (f"{uuid4()}:impact:0",)}
                )
            }
        )
    else:
        changed = review.impacts[0].model_copy(
            update={"impact": "STRENGTHEN"}
            if bad == "positive"
            else {"baseline_status": "UNMATCHED"}
        )

        async def read(_run_id):
            return review.model_copy(update={"impacts": (changed,)})

        monkeypatch.setattr(service._port, "team_review", read)
    with pytest.raises(ApplicationError) as failure:
        await service.save(inp.instrument_id, request)
    assert failure.value.code.value == "THESIS_REVIEW_SOURCE_INVALID"
    assert len((await service.workspace(inp.instrument_id)).versions) == 1 and gateway.calls == 8


async def test_observation_only_source_preserves_legacy_request_hash(database_engine):
    sessions, _, _, _, inp, _, _, service, request = await setup(database_engine)
    await service.save(inp.instrument_id, request)
    payload = request.model_dump(mode="json", exclude={"request_id"})
    payload["review_source"].pop("impact_ids")
    async with sessions() as session:
        event = await session.scalar(
            select(EventLogRecord).where(EventLogRecord.aggregate_id == request.request_id)
        )
        assert event.payload_json["request_hash"] == content_hash(
            {"instrument_id": str(inp.instrument_id), "command": payload}
        )
