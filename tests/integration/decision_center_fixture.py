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

from investment_os.application.policy_schema import InvestmentPolicySchema
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
from investment_os.domain.values import Quantity, UtcTimestamp, Weight
from investment_os.infrastructure.decision_center import ledger_fingerprint
from investment_os.infrastructure.decision_journal import SqlAlchemyDecisionJournalWriter


async def seed_center(
    engine: AsyncEngine,
    *,
    now: datetime | None = None,
    veto: bool = False,
    policy_active: bool = True,
    decision_count: int = 1,
    risk_unknown: bool = False,
    sizing_action_mismatch: bool = False,
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
            approved_at=now - timedelta(hours=1),
            effective_from=now - timedelta(hours=1),
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
            thesis_state="VALID",
            summary="合成已审计论点",
            pillars_json={},
            catalysts_json=[],
            risks_json=[],
            invalidation_conditions_json=[],
            monitoring_conditions_json=[],
            change_reason="NEW_EVIDENCE",
            content_hash="a" * 64,
        )
        await put(
            "committee_session",
            id=ids["committee"],
            instrument_id=ids["instrument"],
            session_type="SYNTHETIC",
            round_count=2,
            status="COMPLETED",
            input_snapshot_hash="a" * 64,
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
            expires_at=now + timedelta(days=1),
            quality_score=Decimal("0.95"),
            freshness_status="FRESH",
            payload_json={"synthetic": True},
            content_hash="a" * 64,
        )
        await put(
            "risk_assessment",
            id=ids["risk"],
            session_id=ids["committee"],
            veto=veto,
            veto_codes=["SYNTHETIC_VETO"] if veto else [],
            hard_flags_json=[
                {
                    "code": "SYNTHETIC_VETO",
                    "kind": "HARD",
                    "severity": "HIGH",
                    "evidence_ids": [str(ids["evidence"])],
                    "release_condition": "synthetic reviewed clearance",
                }
            ]
            if veto
            else [],
            soft_flags_json=[]
            if veto or risk_unknown
            else [
                {
                    "code": "SYNTHETIC_MONITORING",
                    "kind": "SOFT",
                    "severity": "LOW",
                    "evidence_ids": [str(ids["evidence"])],
                    "release_condition": "synthetic monitoring clearance",
                }
            ],
            expires_at=now + timedelta(hours=12),
            content_hash="a" * 64,
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
                input_snapshot_hash="a" * 64,
                started_at=now,
                ended_at=now,
                status="SUCCEEDED",
                token_usage_json={"synthetic": True},
            )
            await put(
                "agent_opinion",
                id=opinion_id,
                agent_run_id=run_id,
                instrument_id=ids["instrument"],
                stance=opinion.stance.value,
                confidence=opinion.confidence.value,
                time_horizon=opinion.time_horizon,
                observations_json=[
                    {"claim": o.claim, "evidence_ids": [str(e) for e in o.evidence_ids]}
                    for o in opinion.observations
                ],
                thesis_impacts_json=[],
                assumptions_json=[],
                risks_json=[],
                invalidation_conditions_json=[],
                unknowns_json=list(opinion.unknowns),
                content_hash="a" * 64,
            )
            await connection.execute(
                text(
                    "INSERT INTO agent_opinion_evidence (agent_opinion_id,evidence_id) "
                    "VALUES (:id,:evidence)"
                ),
                {"id": opinion_id, "evidence": ids["evidence"]},
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

    risk = RiskAssessment(
        ids["risk"],
        1,
        UtcTimestamp(now - timedelta(minutes=1)),
        UtcTimestamp(now + timedelta(hours=12)),
        (
            RiskFlag(
                "SYNTHETIC_MONITORING",
                RiskFlagKind.SOFT,
                RiskSeverity.LOW,
                (ids["evidence"],),
                "合成跟踪条件",
            ),
        ),
    )
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
        "formula": {"version": formula.version},
        "reference_price": "10",
        "ledger_hash": ledger_hash,
    }
    outputs = json.loads(json.dumps(asdict(result), default=str))
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
        next_review_at=UtcTimestamp(now + timedelta(days=1)),
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
