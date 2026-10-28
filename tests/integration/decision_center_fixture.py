"""Synthetic complete PR07 Decision built using the real sizing and Decision writer."""

import asyncio
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from investment_os.application.agent_runtime import AgentRunAttempt, AgentRunResult
from investment_os.application.policy_schema import InvestmentPolicySchema
from investment_os.application.thesis import thesis_content_hash, thesis_content_payload
from investment_os.domain.agent import (
    AgentOpinion,
    AgentRole,
    EvidenceBackedObservation,
    OpinionStance,
)
from investment_os.domain.decision import DecisionClaim, DecisionPosition, InvestmentDecision
from investment_os.domain.enums import (
    Action,
    BucketAction,
    DecisionState,
    PositionBucket,
    RiskIntent,
    ThesisState,
)
from investment_os.domain.portfolio import PortfolioCapacityInputs
from investment_os.domain.risk import RiskAssessment, RiskFlag, RiskFlagKind, RiskSeverity
from investment_os.domain.sizing import SizingFormula, SizingRequest, size_position
from investment_os.domain.thesis import (
    EvidenceBackedClaim,
    PillarStatus,
    ThesisChangeReason,
    ThesisContent,
    ThesisPillar,
)
from investment_os.domain.values import Quantity, UtcTimestamp, Weight
from investment_os.infrastructure.decision_center import ledger_fingerprint
from investment_os.infrastructure.decision_journal import SqlAlchemyDecisionJournalWriter
from investment_os.infrastructure.persistence.agent_observability import (
    agent_opinion_record_from_result,
)
from investment_os.infrastructure.thesis_engine import SqlAlchemyThesisWriter


async def seed_center(
    engine: AsyncEngine,
    *,
    now: datetime | None = None,
    veto: bool = False,
    policy_active: bool = True,
    decision_count: int = 1,
    risk_unknown: bool = False,
    sizing_action_mismatch: bool = False,
    risk_lifetime: timedelta = timedelta(hours=12),
    evidence_lifetime: timedelta = timedelta(days=1),
    review_lifetime: timedelta = timedelta(days=1),
    chain_defect: str | None = None,
    policy_approved_delta: timedelta = -timedelta(hours=1),
    policy_effective_delta: timedelta = -timedelta(hours=1),
) -> dict:
    now = now or datetime.now(UTC)
    ids = {
        key: uuid4()
        for key in (
            "instrument",
            "policy",
            "policy_version",
            "portfolio",
            "strategy",
            "thesis",
            "thesis_version",
            "committee",
            "risk",
            "sizing",
            "evidence",
        )
    }
    correlation = uuid4()
    config = json.loads(
        await asyncio.to_thread(
            Path("config/investment-policy.test-default.json").read_text, encoding="utf-8"
        )
    )
    config["metadata"] = {
        "name": "synthetic-301-only",
        "status": "ACTIVE" if policy_active else "TEST_DEFAULT",
    }
    schema = InvestmentPolicySchema.model_validate_json(json.dumps(config))
    policy = schema.to_domain()

    extra_evidence = uuid4()
    thesis_evidence = (
        extra_evidence if chain_defect == "thesis_expired_reference" else ids["evidence"]
    )
    risk_evidence = extra_evidence if chain_defect == "risk_expired_reference" else ids["evidence"]
    thesis_content = ThesisContent(
        ThesisState.VALID,
        "合成已审计论点",
        (
            ThesisPillar(
                "synthetic-pillar",
                EvidenceBackedClaim("合成来源支柱", (thesis_evidence,)),
                PillarStatus.VALID,
            ),
        ),
        (),
        (),
        (),
        (),
        ThesisChangeReason.NEW_EVIDENCE,
    )
    thesis_payload = thesis_content_payload(thesis_content)
    flags = (
        ()
        if risk_unknown
        else (
            RiskFlag(
                "SYNTHETIC_VETO" if veto else "SYNTHETIC_MONITORING",
                RiskFlagKind.HARD if veto else RiskFlagKind.SOFT,
                RiskSeverity.HIGH if veto else RiskSeverity.LOW,
                (ids["evidence"],),
                "合成跟踪条件",
            ),
        )
    )
    risk = RiskAssessment(
        ids["risk"],
        1,
        UtcTimestamp(now - timedelta(minutes=1)),
        UtcTimestamp(now + risk_lifetime),
        flags,
    )

    use_thesis_writer = chain_defect not in {
        "empty_thesis",
        "missing_thesis_relation",
        "thesis_expired_reference",
        "thesis_asof_unavailable",
        "thesis_asof_missing",
        "thesis_asof_future",
    }
    async with engine.begin() as connection:

        async def put(table: str, **values):
            values.update(created_by="synthetic-301", correlation_id=correlation)
            columns = ",".join(values)
            placeholders = ",".join(
                f"CAST(:{key} AS jsonb)" if isinstance(value, (dict, list)) else f":{key}"
                for key, value in values.items()
            )
            params = {
                k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in values.items()
            }
            await connection.execute(
                text(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"), params
            )

        await put(
            "instrument",
            id=ids["instrument"],
            symbol="SYNTH301",
            exchange="TEST",
            asset_type="EQUITY",
            currency="CNY",
            lot_size=1,
            status="ACTIVE",
        )
        await put(
            "investment_policy",
            id=ids["policy"],
            name=f"synthetic-{ids['policy']}",
            status="ACTIVE",
            version=1,
        )
        await put(
            "investment_policy_version",
            id=ids["policy_version"],
            policy_id=ids["policy"],
            version=1,
            config_json=config,
            approved_by="synthetic-human",
            approved_at=now + policy_approved_delta,
            effective_from=now + policy_effective_delta,
            content_hash="a" * 64,
        )
        await connection.execute(
            text("UPDATE investment_policy SET current_version_id=:version WHERE id=:id"),
            {"id": ids["policy"], "version": ids["policy_version"]},
        )
        await put(
            "portfolio",
            id=ids["portfolio"],
            base_currency="CNY",
            status="ACTIVE",
            cash_balance=10000,
            policy_id=ids["policy"],
        )
        await put(
            "strategy_version",
            id=ids["strategy"],
            version=1,
            status="ACTIVE",
            rules_json={"synthetic": True},
            prompt_bundle_hash="a" * 64,
            code_ref="synthetic-only",
            content_hash="a" * 64,
            approved_by="synthetic-human",
        )
        if not use_thesis_writer:
            await put(
                "investment_thesis",
                id=ids["thesis"],
                instrument_id=ids["instrument"],
                status="VALID",
                version=1,
            )
            await put(
                "thesis_version",
                id=ids["thesis_version"],
                thesis_id=ids["thesis"],
                version=1,
                metadata_json={}
                if chain_defect == "thesis_asof_missing"
                else {
                    "as_of": (
                        now - timedelta(minutes=3)
                        if chain_defect == "thesis_asof_unavailable"
                        else now + timedelta(microseconds=1)
                        if chain_defect == "thesis_asof_future"
                        else now
                    ).isoformat()
                },
                thesis_state="VALID",
                summary="合成已审计论点",
                pillars_json={} if chain_defect == "empty_thesis" else thesis_payload["pillars"],
                catalysts_json=[],
                risks_json=[],
                invalidation_conditions_json=[],
                monitoring_conditions_json=[],
                change_reason="NEW_EVIDENCE",
                content_hash=thesis_content_hash(thesis_content),
            )
        await put(
            "committee_session",
            id=ids["committee"],
            instrument_id=ids["instrument"],
            session_type="SYNTHETIC",
            round_count=2,
            status="COMPLETED",
            input_snapshot_hash="b" * 64
            if chain_defect == "committee_hash_mismatch"
            else ""
            if chain_defect == "committee_hash_missing"
            else "a" * 64,
            started_at=now - timedelta(minutes=1),
            completed_at=now,
        )
        await put(
            "evidence",
            id=ids["evidence"],
            instrument_id=ids["instrument"],
            evidence_type="EVENT",
            source_name="合成审计来源",
            source_locator="synthetic://301/primary",
            source_tier="PRIMARY",
            observed_at=now - timedelta(minutes=2),
            effective_at=now - timedelta(minutes=2),
            available_at=now - timedelta(minutes=2),
            ingested_at=now - timedelta(minutes=2),
            expires_at=now + evidence_lifetime,
            quality_score=Decimal("0.95"),
            freshness_status="FRESH",
            payload_json={"synthetic": True},
            content_hash="a" * 64,
        )
        if chain_defect in {
            "thesis_expired_reference",
            "risk_expired_reference",
            "agent_expired_reference",
            "agent_future_reference",
        }:
            await put(
                "evidence",
                id=extra_evidence,
                instrument_id=ids["instrument"],
                evidence_type="EVENT",
                source_name="合成旧来源",
                source_locator="synthetic://301/expired",
                source_tier="PRIMARY",
                observed_at=now - timedelta(minutes=3),
                effective_at=now - timedelta(minutes=3),
                available_at=now + timedelta(microseconds=1)
                if chain_defect == "agent_future_reference"
                else now - timedelta(minutes=3),
                ingested_at=now - timedelta(minutes=3),
                expires_at=now + timedelta(days=1)
                if chain_defect == "agent_future_reference"
                else now - timedelta(microseconds=1),
                quality_score=Decimal("0.95"),
                freshness_status="FRESH",
                payload_json={"synthetic": True},
                content_hash="b" * 64,
            )
        await put(
            "risk_assessment",
            id=ids["risk"],
            session_id=ids["committee"],
            veto=veto,
            veto_codes=["SYNTHETIC_VETO"] if veto else [],
            hard_flags_json=[
                json.loads(json.dumps(asdict(flag), default=str))
                for flag in flags
                if flag.kind is RiskFlagKind.HARD
            ],
            soft_flags_json=[
                json.loads(json.dumps(asdict(flag), default=str))
                for flag in flags
                if flag.kind is RiskFlagKind.SOFT
            ],
            expires_at=now + risk_lifetime,
            content_hash=risk.content_hash,
        )
        if not use_thesis_writer and chain_defect != "missing_thesis_relation":
            await connection.execute(
                text(
                    "INSERT INTO thesis_version_evidence (thesis_version_id,evidence_id) "
                    "VALUES (:id,:evidence)"
                ),
                {"id": ids["thesis_version"], "evidence": thesis_evidence},
            )
        if flags and chain_defect != "missing_risk_relation":
            await connection.execute(
                text(
                    "INSERT INTO risk_assessment_evidence (risk_assessment_id,evidence_id) "
                    "VALUES (:id,:evidence)"
                ),
                {"id": ids["risk"], "evidence": risk_evidence},
            )
        for role in (
            AgentRole.MACRO,
            AgentRole.INDUSTRY,
            AgentRole.FUNDAMENTAL,
            AgentRole.MARKET_QUANT,
            AgentRole.EVENT,
            AgentRole.DEVILS_ADVOCATE,
        ):
            opinion = AgentOpinion(
                role,
                ids["instrument"],
                OpinionStance.NEUTRAL,
                Weight("0.5"),
                "MONTHS",
                (EvidenceBackedObservation("合成有来源事实", (ids["evidence"],)),),
                (),
                ("合成研究未知项",),
                (),
                as_of=UtcTimestamp(now),
            )
            run_id, opinion_id = uuid4(), uuid4()
            await put(
                "agent_run",
                id=run_id,
                agent_role=role.value,
                model_provider="SYNTHETIC",
                model_name="synthetic-301-fixture",
                prompt_version="synthetic-301-prompt",
                input_snapshot_hash="c" * 64
                if chain_defect == "agent_hash_mismatch"
                else ""
                if chain_defect == "agent_hash_missing"
                else "a" * 64,
                started_at=now,
                ended_at=now,
                status="SUCCEEDED",
                token_usage_json={"synthetic": True},
            )
            normalized = agent_opinion_record_from_result(
                agent_run_id=run_id,
                result=AgentRunResult(
                    opinion,
                    0,
                    ("a" * 64,),
                    (AgentRunAttempt(0, "SYNTHETIC", "synthetic-301-fixture", 0, 0, 0, "a" * 64),),
                ),
                created_by="synthetic-301",
                correlation_id=correlation,
            )
            await put(
                "agent_opinion",
                id=opinion_id,
                agent_run_id=run_id,
                instrument_id=ids["instrument"],
                metadata_json={"agent_opinion_schema_version": "1.0"},
                stance=opinion.stance.value,
                confidence=opinion.confidence.value,
                time_horizon=opinion.time_horizon,
                observations_json=normalized.observations_json,
                thesis_impacts_json=[
                    {
                        "pillar_key": "synthetic-pillar",
                        "impact": "WEAKEN",
                        "reason": "合成反例",
                        "evidence_ids": [str(extra_evidence)],
                    }
                ]
                if chain_defect == "agent_thesis_impact_unlinked"
                else normalized.thesis_impacts_json,
                assumptions_json=normalized.assumptions_json,
                risks_json=[
                    {
                        "code": "SYNTHETIC_EXTRA",
                        "severity": "LOW",
                        "evidence_ids": [str(extra_evidence)],
                    }
                ]
                if chain_defect
                in {"agent_risk_unlinked", "agent_expired_reference", "agent_future_reference"}
                else normalized.risks_json,
                invalidation_conditions_json=normalized.invalidation_conditions_json,
                unknowns_json=normalized.unknowns_json,
                content_hash=normalized.content_hash,
            )
            await connection.execute(
                text(
                    "INSERT INTO agent_opinion_evidence (agent_opinion_id,evidence_id) "
                    "VALUES (:id,:evidence)"
                ),
                {"id": opinion_id, "evidence": ids["evidence"]},
            )
            if chain_defect in {"agent_expired_reference", "agent_future_reference"}:
                await connection.execute(
                    text(
                        "INSERT INTO agent_opinion_evidence (agent_opinion_id,evidence_id) "
                        "VALUES (:id,:evidence)"
                    ),
                    {"id": opinion_id, "evidence": extra_evidence},
                )
            await put(
                "committee_message",
                id=uuid4(),
                session_id=ids["committee"],
                round_number=2 if role is AgentRole.DEVILS_ADVOCATE else 1,
                agent_role=role.value,
                message_type="SYNTHETIC_VALIDATED_OPINION",
                opinion_id=opinion_id,
                payload_json={"synthetic": True},
            )

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    if use_thesis_writer:
        written = await SqlAlchemyThesisWriter(sessions, now=lambda: now).write(
            instrument_id=ids["instrument"],
            content=thesis_content,
            as_of=now,
            correlation_id=correlation,
        )
        ids["thesis"] = written.thesis_id
        ids["thesis_version"] = written.thesis_version_id

    formula = SizingFormula(
        "synthetic-301-v1",
        {intent: Weight(0) for intent in RiskIntent} | {RiskIntent.SMALL: Weight("0.05")},
        Decimal("0.2"),
        Decimal("0.1"),
        Decimal("0.5"),
        Decimal(1),
        Weight("0.5"),
    )
    request = SizingRequest(
        Action.BUY,
        PositionBucket.CORE,
        RiskIntent.SMALL,
        Weight(0),
        Quantity(0),
        Decimal(10000),
        Decimal(10),
        Quantity(1),
        Decimal("0.2"),
        PortfolioCapacityInputs(*(Weight(0) for _ in range(6)), Weight("0.1"), Weight("0.1")),
        policy.position,
        risk,
        ThesisState.VALID,
        UtcTimestamp(now),
    )
    result = size_position(formula, request)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        ledger_hash = await ledger_fingerprint(session, ids["portfolio"])
    inputs = {
        "request": json.loads(json.dumps(asdict(request), default=str)),
        "formula": {
            "version": formula.version,
            "intent_weights": {
                key.value: {"value": str(value.value)}
                for key, value in formula.intent_weights.items()
            },
            "target_volatility": str(formula.target_volatility),
            "volatility_floor": str(formula.volatility_floor),
            "volatility_scale_min": str(formula.volatility_scale_min),
            "volatility_scale_max": str(formula.volatility_scale_max),
            "reduce_fraction": {"value": str(formula.reduce_fraction.value)},
        },
        "reference_price": "10",
        "ledger_hash": ledger_hash,
    }
    outputs = json.loads(json.dumps(asdict(result), default=str))
    if chain_defect == "sizing_shell":
        inputs["request"] = {"action": "BUY", "risk_intent": "SMALL"}
    if chain_defect == "sizing_forged_output":
        outputs["delta_quantity"] = "1000"
    if chain_defect == "sizing_tampered_nav":
        inputs["request"]["nav"] = "20000"
    if sizing_action_mismatch:
        inputs["request"]["action"] = "REDUCE"
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO position_sizing_run "
                "(id,portfolio_id,instrument_id,policy_version_id,input_json,formula_version,"
                "output_json,input_hash,created_by,correlation_id) "
                "VALUES (:id,:portfolio,:instrument,:policy,CAST(:inputs AS jsonb),:formula,"
                "CAST(:outputs AS jsonb),:hash,'synthetic-301',:correlation)"
            ),
            {
                "id": ids["sizing"],
                "portfolio": ids["portfolio"],
                "instrument": ids["instrument"],
                "policy": ids["policy_version"],
                "inputs": json.dumps(inputs),
                "outputs": json.dumps(outputs),
                "formula": formula.version,
                "hash": result.input_hash,
                "correlation": correlation,
            },
        )
    decision = InvestmentDecision(
        instrument_id=ids["instrument"],
        portfolio_id=ids["portfolio"],
        thesis_version_id=ids["thesis_version"],
        policy_version_id=ids["policy_version"],
        strategy_version_id=ids["strategy"],
        risk_assessment_id=ids["risk"],
        position_sizing_run_id=ids["sizing"],
        action=Action.BUY,
        confidence=Weight("0.7"),
        risk_intent=RiskIntent.SMALL,
        position_before=DecisionPosition(Weight(0), Weight(0), Weight(0)),
        position_after_proposed=DecisionPosition(
            result.target_weight, result.target_weight, Weight(0)
        ),
        core_action=BucketAction.BUY,
        tactical_action=BucketAction.NONE,
        reasons=(DecisionClaim("合成证据支持研究", (ids["evidence"],)),),
        risks=(DecisionClaim("合成监控风险", (ids["evidence"],)),),
        watch_conditions=("合成观察条件",),
        invalidation_conditions=("合成失效条件",),
        unknowns=("合成估值不确定性",),
        dissent=("合成反方观点",),
        next_review_at=UtcTimestamp(now + review_lifetime),
        input_snapshot_hash="a" * 64,
        prompt_bundle_version="synthetic-301-prompt",
        formula_version=formula.version,
        committee_session_id=ids["committee"],
        state=DecisionState.PENDING_APPROVAL,
    )
    await SqlAlchemyDecisionJournalWriter(sessions).append_decision(decision, recorded_at=now)
    decisions = [decision.id]
    for _ in range(decision_count - 1):
        extra = replace(decision, id=uuid4())
        await SqlAlchemyDecisionJournalWriter(sessions).append_decision(extra, recorded_at=now)
        decisions.append(extra.id)
    return {
        **ids,
        "decision": decision.id,
        "decisions": decisions,
        "quantity": result.delta_quantity,
        "now": now,
    }
