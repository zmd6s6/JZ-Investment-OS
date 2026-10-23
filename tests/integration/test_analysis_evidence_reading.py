"""按原运行引用核对已保存资料, 只读且不调用任何真实来源或模型。"""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from test_analysis_jobs import jobs_setup

from investment_os.api.app import create_app
from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.research_preview import content_hash
from investment_os.infrastructure.analysis_evidence import SqlAnalysisEvidenceReader
from investment_os.infrastructure.local_access import LocalAccessStore
from investment_os.infrastructure.persistence.models import (
    AnalysisRunRecord,
    AuditLogRecord,
    EventLogRecord,
    EvidenceRecord,
    OutboxEventRecord,
)


async def prepared(engine):
    sessions, _, runs, _, _, jobs, inp = await jobs_setup(engine)
    run = await jobs.submit(uuid4(), inp)
    return sessions, runs, run, inp.evidence_ids[0]


async def totals(sessions):
    async with sessions() as session:
        return [
            await session.scalar(select(func.count()).select_from(model))
            for model in (
                AnalysisRunRecord,
                EvidenceRecord,
                EventLogRecord,
                AuditLogRecord,
                OutboxEventRecord,
            )
        ]


async def test_exact_frozen_citation_reads_original_stored_text_without_writes(database_engine):
    sessions, runs, run, evidence_id = await prepared(database_engine)
    before = await totals(sessions)
    reader = SqlAnalysisEvidenceReader(sessions, now=lambda: run.as_of)
    value = await reader.read(run.id, evidence_id)
    assert value.status == "VERIFIED"
    assert value.citation.evidence_id == evidence_id
    assert (
        value.citation.content_hash == run.payload["input_snapshot"]["evidence"][0]["content_hash"]
    )
    assert value.input_hash == run.payload["input_snapshot"]["input_hash"]
    assert value.untrusted_content and value.texts
    assert value.freshness_at_run == value.freshness_now == "FRESH"
    assert await reader.read(run.id, evidence_id) == value
    assert await totals(sessions) == before
    assert (await runs.get(run.id)).payload == run.payload


async def test_expired_evidence_remains_readable_but_historical_freshness_does_not_change(
    database_engine, monkeypatch
):
    sessions, runs, run, evidence_id = await prepared(database_engine)

    async def no_recent_scan(*args, **kwargs):
        raise AssertionError("citation must use exact identity, not a recent library list")

    monkeypatch.setattr(AsyncSession, "scalars", no_recent_scan)
    reader = SqlAnalysisEvidenceReader(sessions, now=lambda: run.as_of + timedelta(days=400))
    view = await reader.read(run.id, evidence_id)
    assert view.status == "VERIFIED" and view.texts
    assert view.freshness_at_run == "FRESH" and view.freshness_now == "EXPIRED"
    assert (await runs.get(run.id)).payload == run.payload


async def test_foreign_citation_is_rejected_before_reading_the_other_record(
    database_engine, monkeypatch
):
    sessions, _, run, _ = await prepared(database_engine)
    original = AsyncSession.get

    async def read(session, entity, identity, **kwargs):
        if entity is EvidenceRecord:
            raise AssertionError("outside-run Evidence must not be read")
        return await original(session, entity, identity, **kwargs)

    monkeypatch.setattr(AsyncSession, "get", read)
    with pytest.raises(ApplicationError) as error:
        await SqlAnalysisEvidenceReader(sessions).read(run.id, uuid4())
    assert error.value.code == ApplicationErrorCode.ANALYSIS_EVIDENCE_NOT_FOUND


@pytest.mark.parametrize(
    "fault",
    [
        "body",
        "hash",
        "source",
        "time",
        "instrument",
        "snapshot_hash",
        "snapshot_time",
        "snapshot_instrument",
        "duplicate",
        "future",
    ],
)
async def test_corrupt_content_or_frozen_provenance_never_exposes_body(
    database_engine, monkeypatch, fault
):
    sessions, _, run, evidence_id = await prepared(database_engine)
    original = AsyncSession.get

    async def read(session, entity, identity, **kwargs):
        row = await original(session, entity, identity, **kwargs)
        if row is None:
            return None
        if entity is EvidenceRecord and fault in {
            "body",
            "hash",
            "source",
            "time",
            "instrument",
            "future",
        }:
            data = {
                column.name: getattr(row, column.name)
                for column in EvidenceRecord.__table__.columns
            }
            if fault == "body":
                data["payload_json"] = {**row.payload_json, "content": "MUST_NOT_BE_DISPLAYED"}
            if fault == "hash":
                data["content_hash"] = "f" * 64
            if fault == "source":
                data["source_name"] = "wrong-source"
            if fault in {"time", "future"}:
                data["available_at"] = run.as_of + timedelta(days=1)
            if fault == "instrument":
                data["instrument_id"] = uuid4()
            return SimpleNamespace(**data)
        if entity is AnalysisRunRecord and fault in {
            "snapshot_hash",
            "snapshot_time",
            "snapshot_instrument",
            "duplicate",
        }:
            snapshot = {**row.payload_json["input_snapshot"]}
            if fault == "snapshot_hash":
                snapshot["input_hash"] = "f" * 64
            if fault == "snapshot_time":
                snapshot["as_of"] = (run.as_of + timedelta(days=1)).isoformat()
            if fault == "snapshot_instrument":
                snapshot["instrument_id"] = str(uuid4())
            if fault == "duplicate":
                snapshot["evidence"] = snapshot["evidence"] * 2
            if fault != "snapshot_hash":
                snapshot["input_hash"] = content_hash(
                    {k: v for k, v in snapshot.items() if k != "input_hash"}
                )
            return SimpleNamespace(
                id=row.id,
                portfolio_id=row.portfolio_id,
                instrument_id=row.instrument_id,
                as_of=row.as_of,
                payload_json={"input_snapshot": snapshot},
            )
        return row

    monkeypatch.setattr(AsyncSession, "get", read)
    with pytest.raises(ApplicationError) as error:
        await SqlAnalysisEvidenceReader(sessions).read(run.id, evidence_id)
    assert error.value.code == ApplicationErrorCode.ANALYSIS_EVIDENCE_INVALID
    assert "MUST_NOT_BE_DISPLAYED" not in str(error.value)


@pytest.mark.parametrize(
    "case,status",
    [
        ("no_snapshot", "NOT_RECORDED"),
        ("metadata", "SNAPSHOT_ONLY"),
        ("missing", "CONTENT_UNAVAILABLE"),
        ("partial_snapshot", "SNAPSHOT_ONLY"),
    ],
)
async def test_old_or_missing_content_is_explicit_and_never_fetched(
    database_engine, monkeypatch, case, status
):
    sessions, _, run, evidence_id = await prepared(database_engine)
    original = AsyncSession.get

    async def read(session, entity, identity, **kwargs):
        row = await original(session, entity, identity, **kwargs)
        if entity is AnalysisRunRecord and case in {"no_snapshot", "partial_snapshot"}:
            snapshot = dict(row.payload_json["input_snapshot"])
            if case == "partial_snapshot":
                snapshot["evidence"] = [
                    {
                        "evidence_id": str(evidence_id),
                        "content_hash": snapshot["evidence"][0]["content_hash"],
                    }
                ]
                snapshot["input_hash"] = content_hash(
                    {k: v for k, v in snapshot.items() if k != "input_hash"}
                )
            return SimpleNamespace(
                id=row.id,
                portfolio_id=row.portfolio_id,
                instrument_id=row.instrument_id,
                as_of=row.as_of,
                payload_json={} if case == "no_snapshot" else {"input_snapshot": snapshot},
            )
        if entity is EvidenceRecord:
            if case == "missing":
                return None
            if case == "metadata":
                data = {
                    column.name: getattr(row, column.name)
                    for column in EvidenceRecord.__table__.columns
                }
                return SimpleNamespace(**{**data, "metadata_json": {}})
        return row

    monkeypatch.setattr(AsyncSession, "get", read)
    value = await SqlAnalysisEvidenceReader(sessions).read(run.id, evidence_id)
    assert value.status == status and not value.texts


async def test_authenticated_read_only_api_does_not_accept_an_unrelated_evidence(
    database_engine, tmp_path, monkeypatch
):
    sessions, _, run, evidence_id = await prepared(database_engine)
    from investment_os.infrastructure.settings import Settings

    monkeypatch.setattr(
        "investment_os.api.app.get_settings",
        lambda: Settings(api_auth_mode="local_session", local_origin="http://127.0.0.1:18109"),
    )
    app = create_app(
        analysis_evidence_reader=SqlAnalysisEvidenceReader(sessions),
        write_api_token="synthetic-citation-only",
        local_access_store=LocalAccessStore(tmp_path / "synthetic.sqlite3"),
        local_access_origin="http://127.0.0.1:18109",
    )
    path = f"/api/v1/analysis-runs/{run.id}/evidence/{evidence_id}"
    before = await totals(sessions)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:18109"
    ) as client:
        assert (await client.get(path)).status_code == 401
        headers = {"Authorization": "Bearer synthetic-citation-only"}
        response = await client.get(path, headers=headers)
        assert response.status_code == 200 and response.json()["status"] == "VERIFIED"
        assert (
            await client.get(f"/api/v1/analysis-runs/{run.id}/evidence/{uuid4()}", headers=headers)
        ).status_code == 404
        assert (
            await client.get(
                f"/api/v1/analysis-runs/{uuid4()}/evidence/{evidence_id}", headers=headers
            )
        ).status_code == 404
        assert (await client.post(path, headers=headers)).status_code == 405
    assert await totals(sessions) == before
