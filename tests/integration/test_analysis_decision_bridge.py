"""Real Worker Analysis -> explicit atomic Decision -> existing human-only approval chain."""

from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from analysis_decision_fixture import seed_qualification
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_analysis_numeric_pipeline import pipeline

from investment_os.api.analysis_decision_routes import analysis_decision_router
from investment_os.api.write_auth import WriteApiAuthMiddleware
from investment_os.application.analysis_decision_bridge import (
    DecisionBridgeView,
    PrepareAnalysisDecision,
)
from investment_os.application.decision_center import HumanCommand
from investment_os.infrastructure.analysis_decision_bridge import SqlAnalysisDecisionBridge
from investment_os.infrastructure.analysis_decision_models import AnalysisDecisionBridgeRecord
from investment_os.infrastructure.analysis_decision_sources import SqlDecisionQualifications
from investment_os.infrastructure.decision_center import SqlDecisionCenter
from investment_os.infrastructure.persistence.analysis_models import AnalysisRunRecord
from investment_os.infrastructure.persistence.models import (
    AgentOpinionRecord,
    AgentRunRecord,
    DecisionApprovalRecord,
    DecisionExecutionRecord,
    InvestmentDecisionEvidenceRecord,
    InvestmentDecisionRecord,
)

pytestmark = pytest.mark.integration


async def complete_analysis(
    engine, *, include_gate_evidence=True, qualification_options=None, **options
):
    sessions, service, store, runner, command, calls, client, numeric = await pipeline(
        engine, **options
    )
    ids = {
        "portfolio": command.portfolio_id,
        "instrument": command.instrument_id,
        "policy_version": numeric.policy_version_id,
        "snapshot": numeric.snapshot_id,
    }
    ids, _numeric, qualification, strategy = await seed_qualification(
        engine, existing_numeric=(ids, numeric), **(qualification_options or {})
    )
    if include_gate_evidence:
        command = command.model_copy(
            update={"evidence_ids": (*command.evidence_ids, ids["gate_evidence"])}
        )
    queued = await service.start(command)
    await runner.dispatch_due()
    run = await store.get(queued.run_id)
    assert run.error_code is None, run.model_dump(mode="json")
    preparation = PrepareAnalysisDecision(
        request_id=uuid4(),
        run_id=run.run_id,
        qualification_id=qualification.qualification_id,
        expected_input_hash=run.input_hash,
        actor_id="明确合成用户",
        confirm_preparation=True,
    )
    return sessions, store, run, preparation, calls, client, qualification, strategy


async def test_worker_persists_every_validated_opinion_evidence_fk_in_the_original_transaction(
    database_engine,
):
    (
        sessions,
        _store,
        original,
        _command,
        _calls,
        client,
        _qualification,
        _strategy,
    ) = await complete_analysis(database_engine)
    try:
        async with sessions() as session:
            opinions = (
                await session.scalars(
                    select(AgentOpinionRecord)
                    .join(AgentRunRecord, AgentRunRecord.id == AgentOpinionRecord.agent_run_id)
                    .where(AgentRunRecord.correlation_id == original.run_id)
                )
            ).all()
            assert len(opinions) == 7
            for opinion in opinions:
                expected = {
                    str(identifier)
                    for item in [
                        *opinion.observations_json,
                        *opinion.risks_json,
                        *opinion.thesis_impacts_json,
                    ]
                    for identifier in item["evidence_ids"]
                }
                actual = {
                    str(identifier)
                    for identifier in (
                        await session.scalars(
                            text(
                                "SELECT evidence_id FROM agent_opinion_evidence "
                                "WHERE agent_opinion_id=:id"
                            ),
                            {"id": opinion.id},
                        )
                    ).all()
                }
                assert actual == expected and actual
    finally:
        await client.aclose()


@pytest.mark.parametrize("bucket", ["CORE", "TACTICAL"])
async def test_real_analysis_to_decision_preserves_shadow_and_requires_explicit_human_approval(
    database_engine,
    bucket,
):
    (
        sessions,
        store,
        original,
        command,
        calls,
        client,
        _qualification,
        _strategy,
    ) = await complete_analysis(database_engine, bucket=bucket)
    try:
        before_calls = len(calls)
        bridge = SqlAnalysisDecisionBridge(sessions)
        app = FastAPI()
        app.add_middleware(WriteApiAuthMiddleware, token="synthetic-206-write-only")
        app.include_router(analysis_decision_router(bridge, SqlDecisionQualifications(sessions)))
        path = f"/api/v1/analysis/runs/{command.run_id}/decision-preparations"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://synthetic"
        ) as api:
            denied = await api.post(path, json=command.model_dump(mode="json"))
            assert denied.status_code == 401
            saved = await api.post(
                path,
                json=command.model_dump(mode="json"),
                headers={"Authorization": "Bearer synthetic-206-write-only"},
            )
            assert saved.status_code == 200, saved.text
            result = DecisionBridgeView.model_validate(saved.json())
            history = await api.get(path)
            assert history.status_code == 200 and len(history.json()) == 1
        assert result.status == "PENDING_APPROVAL", result.model_dump(mode="json")
        assert result.decision_id is not None and result.revision == 1
        assert await bridge.prepare(command) == result
        assert await bridge.get(original.run_id) == result
        assert len(calls) == before_calls, "preparation must never call a model"
        assert (await store.get(original.run_id)).shadow_decision == original.shadow_decision
        center = SqlDecisionCenter(sessions)
        detail = await center.get(result.decision_id)
        assert not detail.decision.blockers, detail.model_dump(mode="json")
        assert "APPROVE" in detail.allowed_actions
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(InvestmentDecisionRecord))
                == 1
            )
            assert (
                await session.scalar(select(func.count()).select_from(AnalysisDecisionBridgeRecord))
                == 1
            )
            assert (
                await session.scalar(select(func.count()).select_from(DecisionApprovalRecord)) == 0
            )
            assert (
                await session.scalar(select(func.count()).select_from(DecisionExecutionRecord)) == 0
            )
        approved = await center.act(
            result.decision_id,
            "APPROVE",
            HumanCommand(
                request_id=uuid4(),
                expected_revision=detail.decision.revision,
                actor_id="明确合成人工批准者",
                comment="仅测试明确人工批准",
                confirmed=True,
            ),
        )
        assert approved.decision.state == "APPROVED"
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(DecisionExecutionRecord)) == 0
            )
    finally:
        await client.aclose()


@pytest.mark.parametrize("action", ["REJECT", "REVOKE"])
async def test_real_bridge_human_rejection_and_revocation_never_execute(database_engine, action):
    sessions, _store, _original, command, _calls, client, _q, _s = await complete_analysis(
        database_engine
    )
    try:
        result = await SqlAnalysisDecisionBridge(sessions).prepare(command)
        assert result.status == "PENDING_APPROVAL", result.blockers
        center = SqlDecisionCenter(sessions)
        detail = await center.get(result.decision_id)
        actions = ("APPROVE", "REVOKE") if action == "REVOKE" else ("REJECT",)
        for step in actions:
            detail = await center.act(
                result.decision_id,
                step,
                HumanCommand(
                    request_id=uuid4(),
                    expected_revision=detail.decision.revision,
                    actor_id="明确合成人工操作者",
                    comment="验证人工动作不执行",
                    confirmed=True,
                ),
            )
        assert detail.decision.state == ("CANCELLED" if action == "REVOKE" else "REJECTED")
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(DecisionExecutionRecord)) == 0
            )
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "case", ["not_frozen", "unapproved_strategy", "quality_fail", "role_failed"]
)
async def test_unqualified_analysis_only_appends_blocked_attempt_and_preserves_shadow(
    database_engine, case
):
    sessions, store, original, command, calls, client, _q, _s = await complete_analysis(
        database_engine,
        include_gate_evidence=case != "not_frozen",
        qualification_options={"strategy_human_approved": False}
        if case == "unapproved_strategy"
        else {"quality_threshold": "2"}
        if case == "quality_fail"
        else {},
        **({"invalid_role": "MACRO"} if case == "role_failed" else {}),
    )
    try:
        count = len(calls)
        bridge = SqlAnalysisDecisionBridge(sessions)
        result = await bridge.prepare(command)
        assert result.status == "BLOCKED" and result.decision_id is None, result.model_dump(
            mode="json"
        )
        assert result.blockers
        assert await bridge.prepare(command) == result
        assert len(calls) == count
        assert (await store.get(original.run_id)).shadow_decision == original.shadow_decision
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(InvestmentDecisionRecord))
                == 0
            )
            assert (
                await session.scalar(select(func.count()).select_from(DecisionApprovalRecord)) == 0
            )
            assert (
                await session.scalar(select(func.count()).select_from(DecisionExecutionRecord)) == 0
            )
            assert (
                await session.scalar(select(func.count()).select_from(AnalysisDecisionBridgeRecord))
                == 1
            )
    finally:
        await client.aclose()


async def test_bridge_idempotency_revision_and_unique_decision_reject_conflicting_commands(
    database_engine,
):
    sessions, _store, _original, command, _calls, client, _q, _s = await complete_analysis(
        database_engine
    )
    try:
        bridge = SqlAnalysisDecisionBridge(sessions)
        result = await bridge.prepare(command)
        assert result.status == "PENDING_APPROVAL"
        with pytest.raises(ValueError, match="REQUEST_CONFLICT"):
            await bridge.prepare(command.model_copy(update={"actor_id": "不同操作者"}))
        with pytest.raises(ValueError, match="REVISION_CONFLICT"):
            await bridge.prepare(command.model_copy(update={"request_id": uuid4()}))
        with pytest.raises(ValueError, match="ALREADY_HAS_INVESTMENT_DECISION"):
            await bridge.prepare(
                command.model_copy(update={"request_id": uuid4(), "expected_revision": 1})
            )
        assert len(await bridge.history(command.run_id)) == 1
    finally:
        await client.aclose()


async def test_human_approval_rechecks_pending_capacity_after_bridge_creation(database_engine):
    sessions, _store, _original, command, _calls, client, _q, _s = await complete_analysis(
        database_engine
    )
    try:
        result = await SqlAnalysisDecisionBridge(sessions).prepare(command)
        assert result.status == "PENDING_APPROVAL", result.blockers
        other_id = uuid4()
        async with sessions() as session, session.begin():
            original = await session.get(InvestmentDecisionRecord, result.decision_id)
            values = {
                column.name: getattr(original, column.name)
                for column in InvestmentDecisionRecord.__table__.columns
            }
            values.update(
                id=other_id,
                metadata_json={"simulation_only": True, "fixture": "independent-pending-decision"},
            )
            session.add(InvestmentDecisionRecord(**values))
            await session.flush()
            evidence = (
                await session.scalars(
                    select(InvestmentDecisionEvidenceRecord.evidence_id).where(
                        InvestmentDecisionEvidenceRecord.investment_decision_id == original.id
                    )
                )
            ).all()
            session.add_all(
                [
                    InvestmentDecisionEvidenceRecord(
                        investment_decision_id=other_id, evidence_id=identifier
                    )
                    for identifier in evidence
                ]
            )
        center = SqlDecisionCenter(sessions)
        other = await center.get(other_id)
        assert "APPROVE" in other.allowed_actions, other.model_dump(mode="json")
        await center.act(
            other_id,
            "APPROVE",
            HumanCommand(
                request_id=uuid4(),
                expected_revision=other.decision.revision,
                actor_id="合成独立批准者",
                comment="使其他合法待成交暴露变化",
                confirmed=True,
            ),
        )
        detail = await center.get(result.decision_id)
        with pytest.raises(ValueError, match="PENDING_EXPOSURE_CHANGED"):
            await center.act(
                result.decision_id,
                "APPROVE",
                HumanCommand(
                    request_id=uuid4(),
                    expected_revision=detail.decision.revision,
                    actor_id="合成批准者",
                    comment="不得沿用旧容量",
                    confirmed=True,
                ),
            )
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(DecisionApprovalRecord)
                    .where(DecisionApprovalRecord.decision_id == result.decision_id)
                )
                == 0
            )
            assert (
                await session.scalar(select(func.count()).select_from(DecisionExecutionRecord)) == 0
            )
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "offset_us,expected", [(-1, "PENDING_APPROVAL"), (0, "BLOCKED"), (1, "BLOCKED")]
)
async def test_qualification_expiry_is_half_open_at_actual_write(
    database_engine, offset_us, expected
):
    (
        sessions,
        _store,
        _original,
        command,
        _calls,
        client,
        qualification,
        _s,
    ) = await complete_analysis(
        database_engine, qualification_options={"qualification_lifetime": timedelta(minutes=30)}
    )
    try:
        at = qualification.expires_at + timedelta(microseconds=offset_us)
        result = await SqlAnalysisDecisionBridge(sessions, now=lambda: at).prepare(command)
        assert result.status == expected, result.model_dump(mode="json")
        async with sessions() as session:
            assert await session.scalar(
                select(func.count()).select_from(InvestmentDecisionRecord)
            ) == (1 if expected == "PENDING_APPROVAL" else 0)
    finally:
        await client.aclose()


async def test_candidate_and_attempt_rollback_together_if_outbox_emission_fails(
    database_engine, monkeypatch
):
    sessions, _store, _original, command, _calls, client, _q, _s = await complete_analysis(
        database_engine
    )

    async def broken_emit(*_args, **_kwargs):
        raise RuntimeError("synthetic-outbox-failure")

    monkeypatch.setattr("investment_os.infrastructure.analysis_decision_bridge.emit", broken_emit)
    try:
        with pytest.raises(RuntimeError, match="synthetic-outbox-failure"):
            await SqlAnalysisDecisionBridge(sessions).prepare(command)
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(InvestmentDecisionRecord))
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count()).select_from(InvestmentDecisionEvidenceRecord)
                )
                == 0
            )
            assert (
                await session.scalar(select(func.count()).select_from(AnalysisDecisionBridgeRecord))
                == 0
            )
            assert (
                await session.scalar(select(func.count()).select_from(DecisionApprovalRecord)) == 0
            )
    finally:
        await client.aclose()


async def test_persisted_scheduled_shadow_origin_cannot_be_omitted_by_preparation_request(
    database_engine,
):
    sessions, _store, original, command, _calls, client, _q, _s = await complete_analysis(
        database_engine
    )
    try:
        scheduled_id = uuid4()
        async with sessions() as session, session.begin():
            source = await session.get(AnalysisRunRecord, original.run_id)
            values = {
                column.name: getattr(source, column.name)
                for column in AnalysisRunRecord.__table__.columns
            }
            payload = dict(source.queued_input_json)
            payload["command"] = {
                **payload["command"],
                "runtime_authorization": {"intent": "SCHEDULED_SHADOW"},
            }
            values.update(id=scheduled_id, request_id=uuid4(), queued_input_json=payload)
            session.add(AnalysisRunRecord(**values))
        result = await SqlAnalysisDecisionBridge(sessions).prepare(
            command.model_copy(update={"run_id": scheduled_id})
        )
        assert result.status == "BLOCKED"
        assert "SCHEDULED_SHADOW_CANNOT_CREATE_INVESTMENT_DECISION" in result.blockers
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(InvestmentDecisionRecord))
                == 0
            )
    finally:
        await client.aclose()


async def test_high_risk_agent_does_not_become_approvable_from_numeric_pass(
    database_engine, monkeypatch
):
    import test_analysis_numeric_pipeline as pipeline_module

    original_output = pipeline_module.model_output

    def high_risk(wrapper):
        result = original_output(wrapper)
        if wrapper["role"] == "RISK":
            result["risks"] = [
                {
                    "code": "SYNTHETIC_HIGH_RISK",
                    "severity": "HIGH",
                    "evidence_ids": result["observations"][0]["evidence_ids"],
                }
            ]
        return result

    monkeypatch.setattr(pipeline_module, "model_output", high_risk)
    sessions, _store, original, command, _calls, client, _q, _s = await complete_analysis(
        database_engine
    )
    try:
        assert original.risk_sizing.risk_gate == "PASS"
        result = await SqlAnalysisDecisionBridge(sessions).prepare(command)
        assert result.status == "BLOCKED"
        assert "DECISION_UNRESOLVED_HIGH_OR_CRITICAL_AGENT_RISK" in result.blockers
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(InvestmentDecisionRecord))
                == 0
            )
    finally:
        await client.aclose()


async def test_bridge_blocked_attempt_is_database_append_only(database_engine):
    sessions, _store, _original, command, _calls, client, _q, _s = await complete_analysis(
        database_engine, include_gate_evidence=False
    )
    try:
        result = await SqlAnalysisDecisionBridge(sessions).prepare(command)
        assert result.status == "BLOCKED"
        for statement in (
            "UPDATE analysis_decision_bridge SET status=status",
            "DELETE FROM analysis_decision_bridge",
        ):
            with pytest.raises(DBAPIError, match=r"append-only|immutable"):
                async with database_engine.begin() as connection:
                    await connection.execute(text(statement))
        assert await SqlAnalysisDecisionBridge(sessions).get(command.run_id) == result
    finally:
        await client.aclose()
