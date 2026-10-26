"""Read real immutable Thesis tables into fixed analysis requests, synthetic data only."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_analysis_jobs import jobs_setup
from test_thesis_engine import _content

from investment_os.application.analysis_orchestrator import AnalysisRunResult
from investment_os.application.errors import ApplicationError
from investment_os.application.thesis import thesis_content_hash
from investment_os.domain.enums import ThesisState
from investment_os.domain.thesis import ThesisVersion
from investment_os.infrastructure.analysis_thesis import SqlAnalysisThesis
from investment_os.infrastructure.persistence.models import (
    InvestmentThesisRecord,
    ThesisVersionEvidenceRecord,
    ThesisVersionRecord,
)
from investment_os.infrastructure.thesis_engine import SqlAlchemyThesisWriter


async def test_missing_thesis_is_frozen_unknown_without_creating_a_version(database_engine):
    sessions, _, _, product, _, _, inp = await jobs_setup(database_engine)
    prepared = await product.prepare(inp)
    assert prepared.request.thesis_state is ThesisState.UNKNOWN
    assert prepared.request.thesis_version_id is None
    assert prepared.snapshot["thesis"]["version"] is None
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(InvestmentThesisRecord)) == 0
        assert await session.scalar(select(func.count()).select_from(ThesisVersionRecord)) == 0


async def test_queued_thesis_retains_version_and_explicit_retry_reads_new_version(
    database_engine, monkeypatch
):
    sessions, _, runs, _, _, jobs, inp = await jobs_setup(database_engine)
    writer = SqlAlchemyThesisWriter(sessions, now=lambda: datetime.now(UTC))
    first = await writer.write(
        instrument_id=inp.instrument_id, content=_content(inp.evidence_ids), as_of=datetime.now(UTC)
    )
    original = await jobs.submit(uuid4(), inp)
    snapshot = original.payload["input_snapshot"]["thesis"]
    assert snapshot["version"]["id"] == str(first.thesis_version_id)
    second_content = replace(
        _content(inp.evidence_ids, summary="合成后续逻辑"), state=ThesisState.WEAKENING
    )
    second = await writer.write(
        instrument_id=inp.instrument_id, content=second_content, as_of=datetime.now(UTC)
    )
    calls = []

    async def execute(request, **kwargs):
        calls.append(request)
        assert request.thesis_version_id == first.thesis_version_id
        assert request.thesis_state is ThesisState.VALID
        assert request.thesis.version.content.long_term_summary == "Synthetic thesis summary"
        return AnalysisRunResult("FAILED", None, "SYNTHETIC", "合成停止")

    monkeypatch.setattr("investment_os.application.analysis_product.execute_analysis", execute)
    assert await jobs.run_once() and len(calls) == 1
    assert (await runs.get(original.id)).payload["input_snapshot"]["thesis"] == snapshot
    retried = await jobs.retry(original.id, uuid4())
    assert retried.payload["input_snapshot"]["thesis"]["version"]["id"] == str(
        second.thesis_version_id
    )
    assert retried.payload["input_snapshot"]["thesis"]["effective_state"] == "WEAKENING"
    assert (await runs.get(original.id)).payload["input_snapshot"]["thesis"] == snapshot


async def test_analysis_as_of_excludes_future_thesis_and_keeps_past_version(database_engine):
    sessions, _, _, _, _, _, inp = await jobs_setup(database_engine)
    first_time = datetime.now(UTC)
    writer = SqlAlchemyThesisWriter(sessions, now=lambda: first_time)
    first = await writer.write(
        instrument_id=inp.instrument_id, content=_content(inp.evidence_ids), as_of=first_time
    )
    cutoff = datetime.now(UTC)
    future = cutoff + timedelta(hours=1)
    writer = SqlAlchemyThesisWriter(sessions, now=lambda: future)
    await writer.write(
        instrument_id=inp.instrument_id,
        content=_content(inp.evidence_ids, summary="合成未来版本"),
        as_of=future,
    )
    frozen = await SqlAnalysisThesis(sessions).thesis(inp.instrument_id, as_of=cutoff)
    assert frozen.version.id == first.thesis_version_id
    missing = await SqlAnalysisThesis(sessions).thesis(
        inp.instrument_id, as_of=first_time - timedelta(seconds=1)
    )
    assert missing.version is None and missing.state is ThesisState.UNKNOWN


@pytest.mark.parametrize("bad", ["hash", "links", "content", "business_time", "parent", "pointer"])
async def test_invalid_thesis_is_rejected_before_queue_or_model_without_fallback(
    database_engine, bad
):
    sessions, _, _, product, _, _, inp = await jobs_setup(database_engine)
    now = datetime.now(UTC)
    thesis_id, version_id = uuid4(), uuid4()
    payload = _content(inp.evidence_ids)
    record = SqlAlchemyThesisWriter._version_record(
        ThesisVersion(version_id, thesis_id, 1, None, thesis_content_hash(payload), payload),
        created_at=now,
        evaluation_time=now,
        correlation_id=uuid4(),
        diff_payload=None,
    )
    if bad == "hash":
        record.content_hash = "d" * 64
    if bad == "content":
        record.pillars_json = []
    if bad == "business_time":
        record.metadata_json = {"as_of": (now + timedelta(days=1)).isoformat()}
    if bad == "parent":
        record.parent_version_id = version_id
    async with sessions() as session, session.begin():
        thesis = InvestmentThesisRecord(
            id=thesis_id,
            instrument_id=inp.instrument_id,
            status="VALID",
            current_version_id=None,
            created_by="synthetic",
            correlation_id=uuid4(),
        )
        session.add(thesis)
        await session.flush()
        session.add(record)
        await session.flush()
        if bad != "links":
            session.add_all(
                [
                    ThesisVersionEvidenceRecord(thesis_version_id=version_id, evidence_id=eid)
                    for eid in inp.evidence_ids
                ]
            )
        if bad != "pointer":
            thesis.current_version_id = version_id
    with pytest.raises(ApplicationError) as exc:
        await product.prepare(inp)
    assert exc.value.code.value == "ANALYSIS_THESIS_INVALID"
