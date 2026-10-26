"""Human Thesis creation/revision through real SQL transactions and authenticated API."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from test_analysis_jobs import jobs_setup
from test_thesis_engine import _content

from investment_os.api.app import create_app
from investment_os.application.errors import ApplicationError
from investment_os.application.thesis import thesis_content_payload
from investment_os.application.thesis_product import (
    SaveThesisCommand,
    ThesisContentInput,
    ThesisProductService,
)
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    EventLogRecord,
    EvidenceRecord,
    OutboxEventRecord,
    ThesisVersionRecord,
)
from investment_os.infrastructure.thesis_product import SqlThesisProduct


def command(inp, *, base=None, summary="合成长期判断", state="VALID"):
    payload = thesis_content_payload(_content(inp.evidence_ids, summary=summary))
    payload["state"] = state
    return SaveThesisCommand(
        request_id=uuid4(),
        expected_version_id=base,
        content=ThesisContentInput.model_validate(payload),
    )


async def product_setup(engine):
    sessions, *_, inp = await jobs_setup(engine)
    return sessions, ThesisProductService(SqlThesisProduct(sessions)), inp


async def test_thesis_create_replay_revision_noop_and_analysis_version_are_consistent(
    database_engine,
):
    sessions, service, inp = await product_setup(database_engine)
    assert not (await service.workspace(inp.instrument_id)).versions
    first_command = command(inp)
    first = await service.save(inp.instrument_id, first_command)
    assert first.created and first.version == 1
    assert await service.save(inp.instrument_id, first_command) == first
    second = await service.save(
        inp.instrument_id,
        command(inp, base=first.version_id, summary="合成新判断", state="STRENGTHENING"),
    )
    workspace = await service.workspace(inp.instrument_id)
    assert workspace.current_version_id == second.version_id
    assert workspace.versions[0].parent_version_id == first.version_id
    assert workspace.versions[0].semantic_diff["summary_changed"]
    assert workspace.versions[1].content_hash == first.content_hash
    assert workspace.versions[1].content.long_term_summary == "合成长期判断"
    no_change = await service.save(
        inp.instrument_id,
        command(inp, base=second.version_id, summary="合成新判断", state="STRENGTHENING"),
    )
    assert not no_change.created and no_change.version_id == second.version_id
    assert len((await service.workspace(inp.instrument_id)).versions) == 2
    async with sessions() as session:
        audits = list(
            await session.scalars(
                select(AuditLogRecord)
                .where(AuditLogRecord.operation == "THESIS_PRODUCT_SAVED")
                .order_by(AuditLogRecord.occurred_at)
            )
        )
        assert len(audits) == 3
        assert (
            audits[1].before_hash == first.content_hash
            and audits[1].after_hash == second.content_hash
        )
        events = list(
            await session.scalars(
                select(EventLogRecord).where(EventLogRecord.event_type == "THESIS_PRODUCT_SAVED")
            )
        )
        assert len(events) == 3
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OutboxEventRecord)
                .where(OutboxEventRecord.event_id.in_([e.id for e in events]))
            )
            == 3
        )
    from investment_os.infrastructure.analysis_thesis import SqlAnalysisThesis

    assert (
        await SqlAnalysisThesis(sessions).thesis(inp.instrument_id, as_of=datetime.now(UTC))
    ).version.id == second.version_id


@pytest.mark.parametrize("initial", [True, False])
async def test_concurrent_thesis_save_accepts_one_base_and_rolls_back_other(
    database_engine, initial
):
    _, service, inp = await product_setup(database_engine)
    base = None if initial else (await service.save(inp.instrument_id, command(inp))).version_id
    cmds = [command(inp, base=base, summary=f"合成并发 {i}") for i in range(2)]
    results = await asyncio.gather(
        *(service.save(inp.instrument_id, c) for c in cmds), return_exceptions=True
    )
    assert sum(not isinstance(r, Exception) for r in results) == 1
    assert next(r for r in results if isinstance(r, Exception)).code.value == "THESIS_EDIT_CONFLICT"
    assert len((await service.workspace(inp.instrument_id)).versions) == (1 if initial else 2)


async def test_concurrent_same_request_creates_one_version_and_one_receipt(database_engine):
    sessions, service, inp = await product_setup(database_engine)
    request = command(inp)
    results = await asyncio.gather(*(service.save(inp.instrument_id, request) for _ in range(3)))
    assert results[0] == results[1] == results[2]
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(ThesisVersionRecord)) == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventLogRecord)
                .where(EventLogRecord.event_type == "THESIS_PRODUCT_SAVED")
            )
            == 1
        )


async def test_request_reuse_stale_editor_and_broken_shortcut_are_rejected(database_engine):
    _, service, inp = await product_setup(database_engine)
    original = command(inp)
    saved = await service.save(inp.instrument_id, original)
    for bad in [command(inp), command(inp, base=uuid4())]:
        with pytest.raises(ApplicationError) as exc:
            await service.save(inp.instrument_id, bad)
        assert exc.value.code.value == "THESIS_EDIT_CONFLICT"
    wrong = command(inp, base=saved.version_id).model_copy(
        update={"request_id": original.request_id}
    )
    with pytest.raises(ApplicationError) as exc:
        await service.save(inp.instrument_id, wrong)
    assert exc.value.code.value == "THESIS_REQUEST_CONFLICT"
    weakened = await service.save(
        inp.instrument_id, command(inp, base=saved.version_id, state="WEAKENING")
    )
    broken = await service.save(
        inp.instrument_id, command(inp, base=weakened.version_id, state="BROKEN")
    )
    with pytest.raises(ApplicationError) as exc:
        await service.save(inp.instrument_id, command(inp, base=broken.version_id))
    assert exc.value.code.value == "THESIS_WRITE_INVALID"
    assert (await service.workspace(inp.instrument_id)).current_version_id == broken.version_id


@pytest.mark.parametrize(
    "bad", ["missing", "foreign", "future", "not_ingested", "expired", "stale"]
)
async def test_invalid_evidence_rolls_back_all_thesis_records(database_engine, bad):
    sessions, service, inp = await product_setup(database_engine)
    now = datetime.now(UTC)
    eid = uuid4()
    if bad != "missing":
        async with sessions() as session, session.begin():
            session.add(
                EvidenceRecord(
                    id=eid,
                    instrument_id=None if bad == "foreign" else inp.instrument_id,
                    evidence_type="NEWS",
                    source_name="synthetic",
                    source_locator=f"synthetic://{eid}",
                    source_tier="PRIMARY",
                    observed_at=now,
                    effective_at=now,
                    available_at=now + timedelta(days=1) if bad == "future" else now,
                    ingested_at=now + timedelta(days=1) if bad == "not_ingested" else now,
                    expires_at=now if bad == "expired" else None,
                    freshness_status="STALE" if bad == "stale" else "FRESH",
                    quality_score="0.5",
                    payload_json={},
                    content_hash="b" * 64,
                    created_by="synthetic",
                    correlation_id=uuid4(),
                )
            )
    if bad == "foreign":
        # A generic macro item is intentionally allowed; a different instrument is not.
        from investment_os.infrastructure.persistence.models import InstrumentRecord

        other = uuid4()
        async with sessions() as session, session.begin():
            session.add(
                InstrumentRecord(
                    id=other,
                    symbol="629991",
                    exchange="SSE",
                    asset_type="EQUITY",
                    currency="CNY",
                    lot_size=1,
                    status="ACTIVE",
                    created_by="synthetic",
                    correlation_id=uuid4(),
                )
            )
        async with sessions() as session, session.begin():
            foreign_id = uuid4()
            session.add(
                EvidenceRecord(
                    id=foreign_id,
                    instrument_id=other,
                    evidence_type="NEWS",
                    source_name="synthetic",
                    source_locator=f"synthetic://{foreign_id}",
                    source_tier="PRIMARY",
                    observed_at=now,
                    effective_at=now,
                    available_at=now,
                    ingested_at=now,
                    expires_at=None,
                    freshness_status="FRESH",
                    quality_score="0.5",
                    payload_json={},
                    content_hash="c" * 64,
                    created_by="synthetic",
                    correlation_id=uuid4(),
                )
            )
        eid = foreign_id
    data = command(inp).model_dump(mode="json")
    for key in ("catalysts", "risks"):
        data["content"][key] = []
    data["content"]["pillars"][0]["claim"]["evidence_ids"] = [str(eid)]
    with pytest.raises(ApplicationError) as exc:
        await service.save(inp.instrument_id, SaveThesisCommand.model_validate(data))
    assert exc.value.code.value == "THESIS_EVIDENCE_INVALID"
    assert not (await service.workspace(inp.instrument_id)).versions


async def test_outbox_failure_rolls_back_version_pointer_and_receipt(database_engine, monkeypatch):
    _, service, inp = await product_setup(database_engine)
    request = command(inp)

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic receipt failure")

    with monkeypatch.context() as patch:
        patch.setattr("investment_os.infrastructure.thesis_product.append_event", fail)
        with pytest.raises(RuntimeError):
            await service.save(inp.instrument_id, request)
    assert not (await service.workspace(inp.instrument_id)).versions
    assert (await service.save(inp.instrument_id, request)).version == 1


async def test_unreadable_current_version_rejects_revision_without_overwriting(
    database_engine, monkeypatch
):
    _, service, inp = await product_setup(database_engine)
    saved = await service.save(inp.instrument_id, command(inp))

    def unreadable(*args):
        raise ValueError("synthetic malformed stored content")

    with monkeypatch.context() as patch:
        patch.setattr(
            "investment_os.infrastructure.thesis_product.thesis_content_from_record", unreadable
        )
        with pytest.raises(ApplicationError) as exc:
            await service.save(inp.instrument_id, command(inp, base=saved.version_id))
        assert exc.value.code.value == "THESIS_WRITE_INVALID"
        with pytest.raises(ApplicationError) as exc:
            await service.workspace(inp.instrument_id)
        assert exc.value.code.value == "THESIS_WRITE_INVALID"
    workspace = await service.workspace(inp.instrument_id)
    assert workspace.current_version_id == saved.version_id and len(workspace.versions) == 1


async def test_api_thesis_authentication_strict_schema_and_conflict_errors(database_engine):
    _, service, inp = await product_setup(database_engine)
    app = create_app(thesis_product_service=service, write_api_token="synthetic-thesis-write")
    path = f"/api/v1/theses/{inp.instrument_id}/versions"
    data = command(inp).model_dump(mode="json")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.post(path, json=data)).status_code == 401
        headers = {"Authorization": "Bearer synthetic-thesis-write"}
        assert (
            await client.post(path, json={**data, "activate_strategy": True}, headers=headers)
        ).status_code == 422
        response = await client.post(path, json=data, headers=headers)
        assert response.status_code == 200
        assert (await client.post(path, json=data, headers=headers)).json() == response.json()
        conflict = await client.post(
            path, json=command(inp).model_dump(mode="json"), headers=headers
        )
        assert (
            conflict.status_code == 409
            and conflict.json()["detail"]["code"] == "THESIS_EDIT_CONFLICT"
        )
        workspace = await client.get(f"/api/v1/theses/{inp.instrument_id}/workspace")
        assert workspace.status_code == 200 and len(workspace.json()["versions"]) == 1
