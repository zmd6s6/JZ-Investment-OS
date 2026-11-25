"""Real PostgreSQL/API content commands: atomicity, time, concurrency and immutable receipts."""

import asyncio
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_analysis_history import database_snapshot
from test_thesis_engine import NOW, _append_evidence, _insert_instrument

from investment_os.api.app import create_app
from investment_os.api.thesis_workspace_routes import thesis_workspace_router
from investment_os.api.write_auth import WriteApiAuthMiddleware
from investment_os.application.thesis_workspace import ConditionInput, ThesisCommand
from investment_os.domain.enums import ThesisState
from investment_os.domain.thesis import ThesisChangeReason
from investment_os.infrastructure.persistence.models import EvidenceRecord
from investment_os.infrastructure.persistence.repositories import AuditRepository, OutboxRepository
from investment_os.infrastructure.thesis_engine import (
    SqlAlchemyThesisReader,
    SqlAlchemyThesisWriter,
)
from investment_os.infrastructure.thesis_workspace import SqlThesisWorkspace

pytestmark = pytest.mark.integration


async def prepare(engine, **evidence_updates):
    instrument = uuid4()
    await _insert_instrument(engine, instrument)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    evidence = await _append_evidence(
        sessions, instrument_id=instrument, available_at=NOW - timedelta(days=1)
    )
    # Test setup updates must precede append-only insertion; use a separate new record.
    if evidence_updates:
        wrong_instrument = evidence_updates.get("instrument_id")
        if wrong_instrument is not None and wrong_instrument != instrument:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO instrument (id, symbol, exchange, asset_type, currency, "
                        "lot_size, status, created_by, correlation_id) VALUES "
                        "(:id, :symbol, 'TEST', 'EQUITY', 'CNY', 1, "
                        "'ACTIVE', 'pytest', :correlation)"
                    ),
                    {"id": wrong_instrument, "symbol": str(uuid4()), "correlation": uuid4()},
                )
        async with sessions() as session:
            old = await session.get(EvidenceRecord, evidence)
            values = {c.name: getattr(old, c.name) for c in EvidenceRecord.__table__.columns}
            values.update(
                evidence_updates, id=uuid4(), source_locator=f"synthetic://thesis/{uuid4()}"
            )
            row = EvidenceRecord(**values)
            session.add(row)
            await session.commit()
            evidence = row.id
    command = ThesisCommand.model_validate(
        {
            "request_id": str(uuid4()),
            "instrument_id": str(instrument),
            "expected_version_id": None,
            "expected_content_hash": None,
            "actor_name": "合成研究员",
            "draft": {
                "state": "UNKNOWN",
                "long_term_summary": "合成人工逻辑 A",
                "pillars": [
                    {
                        "key": "P1",
                        "claim": {"description": "合成事实", "evidence_ids": [str(evidence)]},
                        "status": "AT_RISK",
                    }
                ],
                "catalysts": [],
                "risks": [],
                "invalidation_conditions": [],
                "monitoring_conditions": ["合成监控"],
                "change_reason": "HUMAN_CORRECTION",
            },
        }
    )
    return sessions, SqlThesisWorkspace(sessions, now=lambda: NOW), command


def revision(command, receipt, **draft):
    return command.model_copy(
        update={
            "request_id": uuid4(),
            "expected_version_id": receipt.saved.version_id,
            "expected_content_hash": receipt.saved.content_hash,
            "draft": command.draft.model_copy(update=draft),
        }
    )


async def test_initial_unknown_preview_zero_writes_revision_parent_hash_and_original_sources(
    database_engine,
):
    sessions, store, command = await prepare(database_engine)
    before = await database_snapshot(sessions)
    preview = await store.preview(command)
    assert preview.material and preview.differences == {"initial_creation": True}
    assert (await store.read(command.instrument_id)).current is None
    assert await database_snapshot(sessions) == before
    a = await store.save(command)
    assert a.created and a.saved.version == 1 and a.saved.draft.state == ThesisState.UNKNOWN
    a_snapshot = a.saved.model_dump(mode="json")
    b = await store.save(revision(command, a, long_term_summary="合成人工逻辑 B"))
    assert b.saved.version == 2 and b.saved.parent_version_id == a.saved.version_id
    view = await store.read(command.instrument_id)
    assert view.current == b.saved and view.history[1].model_dump(mode="json") == a_snapshot
    assert view.history[0].semantic_diff["summary_changed"] is True
    assert view.evidence[0].observed_at < NOW and view.evidence[0].ingested_at < NOW
    legacy = SqlAlchemyThesisReader(sessions)
    assert (await legacy.current_for_instrument(command.instrument_id)).version == 2
    assert len(await legacy.history_for_instrument(command.instrument_id)) == 2


@pytest.mark.parametrize("state", ["VALID", "STRENGTHENING", "WEAKENING", "BROKEN"])
async def test_initial_non_unknown_forbidden_without_effects(database_engine, state):
    sessions, store, command = await prepare(database_engine)
    before = await database_snapshot(sessions)
    bad = command.model_copy(
        update={
            "draft": command.draft.model_copy(
                update={
                    "state": ThesisState(state),
                    "invalidation_conditions": (
                        ConditionInput(
                            condition="test", measurement="test", threshold="1", window="test"
                        ),
                    ),
                }
            )
        }
    )
    for action in (store.preview, store.save):
        with pytest.raises(ValueError, match="THESIS_STATE_CHANGE_FORBIDDEN"):
            await action(bad)
    assert await database_snapshot(sessions) == before


@pytest.mark.parametrize("state", ["VALID", "STRENGTHENING", "WEAKENING", "BROKEN"])
async def test_same_existing_state_content_allowed_but_no_promotion_or_broken_recovery(
    database_engine, state
):
    sessions, store, command = await prepare(database_engine)
    from test_thesis_engine import _content

    content = _content(command.draft.domain().evidence_ids)
    from dataclasses import replace

    await SqlAlchemyThesisWriter(sessions, now=lambda: NOW - timedelta(seconds=1)).write(
        instrument_id=command.instrument_id,
        content=replace(content, state=ThesisState(state)),
        as_of=NOW,
    )
    current = (await store.read(command.instrument_id)).current
    cmd = command.model_copy(
        update={
            "expected_version_id": current.version_id,
            "expected_content_hash": current.content_hash,
            "draft": current.draft.model_copy(update={"long_term_summary": "人工同状态修订"}),
        }
    )
    result = await store.save(cmd)
    assert result.saved.draft.state == state and result.saved.version == 2
    forbidden = revision(cmd, result, state=ThesisState.UNKNOWN)
    with pytest.raises(ValueError, match="THESIS_STATE_CHANGE_FORBIDDEN"):
        await store.save(forbidden)


@pytest.mark.parametrize("field", ["observed_at", "effective_at", "available_at", "ingested_at"])
async def test_future_each_business_time_rejected_at_preview_and_save(database_engine, field):
    sessions, store, cmd = await prepare(
        database_engine, **{field: NOW + timedelta(microseconds=1)}
    )
    before = await database_snapshot(sessions)
    for action in (store.preview, store.save):
        with pytest.raises(ValueError, match="THESIS_EVIDENCE_FUTURE"):
            await action(cmd)
    assert await database_snapshot(sessions) == before


@pytest.mark.parametrize(
    "updates,code",
    [
        ({"expires_at": NOW}, "EXPIRED"),
        ({"expires_at": NOW - timedelta(microseconds=1)}, "EXPIRED"),
        ({"quality_score": Decimal("0")}, "INVALID"),
        ({"freshness_status": "STALE"}, "INVALID"),
        ({"freshness_status": "NOT_YET_AVAILABLE"}, "INVALID"),
        ({"instrument_id": uuid4()}, "WRONG_INSTRUMENT"),
    ],
)
async def test_invalid_expired_quality_scope_rejected_atomically(database_engine, updates, code):
    sessions, store, cmd = await prepare(database_engine, **updates)
    before = await database_snapshot(sessions)
    for action in (store.preview, store.save):
        with pytest.raises(ValueError, match=f"THESIS_EVIDENCE_{code}"):
            await action(cmd)
    assert await database_snapshot(sessions) == before


async def test_exact_availability_and_just_before_expiry_neutral_evidence_allowed(database_engine):
    _, store, cmd = await prepare(
        database_engine,
        instrument_id=None,
        observed_at=NOW,
        effective_at=NOW,
        available_at=NOW,
        ingested_at=NOW,
        expires_at=NOW + timedelta(microseconds=1),
    )
    assert (await store.save(cmd)).created


async def test_missing_evidence_and_instrument_fail_closed(database_engine):
    _sessions, store, cmd = await prepare(database_engine)
    bad = cmd.model_copy(update={"instrument_id": uuid4()})
    with pytest.raises(ValueError, match="THESIS_INSTRUMENT_NOT_FOUND"):
        await store.save(bad)
    draft = cmd.draft.model_dump(mode="json")
    draft["pillars"][0]["claim"]["evidence_ids"] = [str(uuid4())]
    bad = ThesisCommand.model_validate({**cmd.model_dump(mode="json"), "draft": draft})
    with pytest.raises(ValueError, match="THESIS_EVIDENCE_MISSING"):
        await store.save(bad)
    assert (await store.read(cmd.instrument_id)).current is None


async def test_successful_request_receipt_replays_after_later_expiry_without_new_effects(
    database_engine,
):
    sessions, store, cmd = await prepare(database_engine, expires_at=NOW + timedelta(seconds=1))
    receipt = await store.save(cmd)
    before = await database_snapshot(sessions)
    expired = SqlThesisWorkspace(sessions, now=lambda: NOW + timedelta(seconds=2))
    assert not next(
        e
        for e in (await expired.read(cmd.instrument_id)).evidence
        if e.evidence_id in cmd.draft.domain().evidence_ids
    ).eligible
    assert await expired.save(cmd) == receipt
    assert await database_snapshot(sessions) == before
    with pytest.raises(ValueError, match="THESIS_EVIDENCE_EXPIRED"):
        await expired.preview(revision(cmd, receipt))


async def test_request_content_instrument_actor_and_baseline_conflicts(database_engine):
    sessions, store, cmd = await prepare(database_engine)
    receipt = await store.save(cmd)
    before = await database_snapshot(sessions)
    for bad in (
        cmd.model_copy(update={"instrument_id": uuid4()}),
        cmd.model_copy(update={"actor_name": "另一研究员"}),
        cmd.model_copy(
            update={"draft": cmd.draft.model_copy(update={"long_term_summary": "其他内容"})}
        ),
        cmd.model_copy(
            update={
                "expected_version_id": receipt.saved.version_id,
                "expected_content_hash": receipt.saved.content_hash,
            }
        ),
    ):
        with pytest.raises(ValueError, match="THESIS_REQUEST_CONFLICT"):
            await store.save(bad)
    assert await database_snapshot(sessions) == before


async def test_stale_null_and_wrong_hash_baselines_reject_without_effects(database_engine):
    sessions, store, cmd = await prepare(database_engine)
    a = await store.save(cmd)
    before = await database_snapshot(sessions)
    for bad in (
        cmd.model_copy(update={"request_id": uuid4()}),
        revision(cmd, a).model_copy(update={"expected_content_hash": "f" * 64}),
        revision(cmd, a).model_copy(update={"expected_version_id": uuid4()}),
    ):
        with pytest.raises(ValueError, match="THESIS_BASELINE_CONFLICT"):
            await store.save(bad)
    assert await database_snapshot(sessions) == before


async def test_semantic_noop_does_not_create_version_and_its_receipt_replays(database_engine):
    sessions, store, cmd = await prepare(database_engine)
    a = await store.save(cmd)
    noop = revision(cmd, a, change_reason=ThesisChangeReason.NEW_EVIDENCE)
    assert not (await store.preview(noop)).material
    receipt = await store.save(noop)
    assert not receipt.created and receipt.saved == a.saved
    before = await database_snapshot(sessions)
    assert await store.save(noop) == receipt
    async with sessions() as session:
        assert await session.scalar(text("SELECT count(*) FROM thesis_version")) == 1
    assert await database_snapshot(sessions) == before


async def test_concurrent_first_creation_and_revisions_have_one_winner_without_partial_effects(
    database_engine,
):
    sessions, store, cmd = await prepare(database_engine)
    results = await asyncio.gather(
        store.save(cmd),
        store.save(cmd.model_copy(update={"request_id": uuid4()})),
        return_exceptions=True,
    )
    winners = [r for r in results if not isinstance(r, Exception)]
    assert len(winners) == 1 and "THESIS_BASELINE_CONFLICT" in str(
        next(r for r in results if isinstance(r, Exception))
    )
    a = winners[0]
    rev = revision(cmd, a, long_term_summary="新版本")
    results = await asyncio.gather(
        store.save(rev),
        store.save(rev.model_copy(update={"request_id": uuid4()})),
        return_exceptions=True,
    )
    assert sum(not isinstance(r, Exception) for r in results) == 1
    async with sessions() as session:
        for table in (
            "thesis_version",
            "thesis_command_receipt",
            "audit_log",
            "event_log",
            "outbox_event",
        ):
            assert await session.scalar(text(f"SELECT count(*) FROM {table}")) == 2


async def test_concurrent_identical_request_commits_exactly_once(database_engine):
    sessions, store, cmd = await prepare(database_engine)
    a, b = await asyncio.gather(store.save(cmd), store.save(cmd))
    assert a == b
    async with sessions() as session:
        for table in (
            "thesis_version",
            "thesis_command_receipt",
            "audit_log",
            "event_log",
            "outbox_event",
        ):
            assert await session.scalar(text(f"SELECT count(*) FROM {table}")) == 1


@pytest.mark.parametrize(
    "repository,method", [(AuditRepository, "append"), (OutboxRepository, "add")]
)
async def test_audit_outbox_failure_rolls_back_version_pointer_links_and_receipt(
    database_engine, monkeypatch, repository, method
):
    sessions, store, cmd = await prepare(database_engine)
    before = await database_snapshot(sessions)

    async def fail(*args, **kwargs):
        raise RuntimeError("synthetic atomic fault")

    monkeypatch.setattr(repository, method, fail)
    with pytest.raises(RuntimeError, match="synthetic atomic fault"):
        await store.save(cmd)
    assert await database_snapshot(sessions) == before


async def test_expiry_after_last_await_rolls_back_every_effect(database_engine):
    sessions, _, cmd = await prepare(database_engine, expires_at=NOW + timedelta(seconds=1))
    before = await database_snapshot(sessions)
    ticks = iter([NOW, NOW + timedelta(seconds=1)])
    store = SqlThesisWorkspace(sessions, now=lambda: next(ticks))
    with pytest.raises(ValueError, match="THESIS_EVIDENCE_EXPIRED"):
        await store.save(cmd)
    assert await database_snapshot(sessions) == before


async def test_preview_does_not_authorize_later_expired_save(database_engine):
    sessions, store, cmd = await prepare(database_engine, expires_at=NOW + timedelta(seconds=1))
    await store.preview(cmd)
    before = await database_snapshot(sessions)
    with pytest.raises(ValueError, match="THESIS_EVIDENCE_EXPIRED"):
        await SqlThesisWorkspace(sessions, now=lambda: NOW + timedelta(seconds=1)).save(cmd)
    assert await database_snapshot(sessions) == before


async def test_authenticated_api_strict_schema_write_denial_and_existing_reads(database_engine):
    sessions, store, cmd = await prepare(database_engine)
    app = FastAPI()
    app.add_middleware(WriteApiAuthMiddleware, token="synthetic-thesis-only")
    app.include_router(thesis_workspace_router(store))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        assert (
            await client.get(f"/api/v1/thesis-workspace/{cmd.instrument_id}")
        ).status_code == 200
        for headers in ({}, {"Authorization": "Bearer incorrect"}):
            for action in ("preview", "save"):
                assert (
                    await client.post(
                        f"/api/v1/thesis-workspace/{action}",
                        json=cmd.model_dump(mode="json"),
                        headers=headers,
                    )
                ).status_code == 401
        headers = {"Authorization": "Bearer synthetic-thesis-only"}
        for extra in (
            {"as_of": NOW.isoformat()},
            {"full_review_completed": True},
            {"schema_version": "2.0"},
        ):
            assert (
                await client.post(
                    "/api/v1/thesis-workspace/save",
                    json={**cmd.model_dump(mode="json"), **extra},
                    headers=headers,
                )
            ).status_code == 422
        bad = cmd.model_dump(mode="json")
        bad["draft"]["pillars"][0]["claim"]["evidence_ids"] = []
        rejected = await client.post("/api/v1/thesis-workspace/save", json=bad, headers=headers)
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] == "THESIS_INPUT_INVALID"
        assert "引用证据" in rejected.json()["detail"]["message"]
        assert (
            await client.post(
                "/api/v1/thesis-workspace/preview",
                json=cmd.model_dump(mode="json"),
                headers=headers,
            )
        ).status_code == 200
        result = await client.post(
            "/api/v1/thesis-workspace/save", json=cmd.model_dump(mode="json"), headers=headers
        )
        assert result.status_code == 200
        assert result.json()["saved"]["draft"]["state"] == "UNKNOWN"
        assert (await client.get(f"/api/v1/thesis-workspace/{cmd.instrument_id}")).json()[
            "current"
        ]["version"] == 1
        assert (await client.get(f"/api/v1/thesis-workspace/{uuid4()}")).status_code == 422
        assert (await client.get("/api/v1/thesis-workspace/invalid")).status_code == 422
    # Existing GET response shape remains unchanged.
    legacy = create_app(thesis_reader=SqlAlchemyThesisReader(sessions), thesis_workspace=store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(legacy), base_url="http://test"
    ) as client:
        assert (await client.get(f"/api/v1/theses/{cmd.instrument_id}")).status_code == 200
        assert (
            len(
                (await client.get(f"/api/v1/theses/{cmd.instrument_id}/versions")).json()[
                    "versions"
                ]
            )
            == 1
        )


async def test_receipt_and_old_versions_database_immutable(database_engine):
    from sqlalchemy.exc import DBAPIError

    sessions, store, cmd = await prepare(database_engine)
    await store.save(cmd)
    for table in ("thesis_version", "thesis_version_evidence", "thesis_command_receipt"):
        async with sessions() as session:
            with pytest.raises(DBAPIError, match=r"append-only|immutable"):
                await session.execute(text(f"DELETE FROM {table}"))
            await session.rollback()


async def test_read_zero_effects_and_server_utc_saved_no_backdate(database_engine):
    sessions, store, cmd = await prepare(database_engine)
    receipt = await store.save(cmd)
    assert receipt.saved.created_at == NOW
    before = await database_snapshot(sessions)
    assert (await store.read(cmd.instrument_id)).current == receipt.saved
    assert await database_snapshot(sessions) == before


async def test_database_quality_over_one_rejected_before_command_can_use_it(database_engine):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError, match="quality_range"):
        await prepare(database_engine, quality_score=Decimal("1.01"))


async def test_previous_revision_upgrade_retains_legacy_versions_and_receipt_recovery(
    database_engine,
):
    from alembic import command as migration
    from alembic.config import Config
    from test_thesis_engine import _content

    sessions, store, cmd = await prepare(database_engine)
    await SqlAlchemyThesisWriter(sessions, now=lambda: NOW - timedelta(seconds=1)).write(
        instrument_id=cmd.instrument_id,
        content=_content(cmd.draft.domain().evidence_ids),
        as_of=NOW,
    )
    original = (await store.read(cmd.instrument_id)).current
    await database_engine.dispose()
    await asyncio.to_thread(migration.downgrade, Config("alembic.ini"), "20261117_0028")
    await asyncio.to_thread(migration.upgrade, Config("alembic.ini"), "head")
    assert (await store.read(cmd.instrument_id)).current == original
    updated = cmd.model_copy(
        update={
            "expected_version_id": original.version_id,
            "expected_content_hash": original.content_hash,
            "draft": original.draft.model_copy(update={"long_term_summary": "人工修订新迁移"}),
        }
    )
    receipt = await store.save(updated)
    assert receipt.saved.parent_version_id == original.version_id
    before = await database_snapshot(sessions)
    with pytest.raises(RuntimeError, match="Thesis receipts exist"):
        await asyncio.to_thread(migration.downgrade, Config("alembic.ini"), "20261117_0028")
    assert await database_snapshot(sessions) == before
    assert await store.save(updated) == receipt


async def test_missing_configured_write_token_rejects_preview_and_save(database_engine):
    sessions, store, cmd = await prepare(database_engine)
    before = await database_snapshot(sessions)
    app = FastAPI()
    app.add_middleware(WriteApiAuthMiddleware, token=None)
    app.include_router(thesis_workspace_router(store))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        for action in ("preview", "save"):
            assert (
                await client.post(
                    f"/api/v1/thesis-workspace/{action}", json=cmd.model_dump(mode="json")
                )
            ).status_code == 503
    assert await database_snapshot(sessions) == before
