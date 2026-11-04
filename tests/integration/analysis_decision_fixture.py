"""Explicit complete synthetic Strategy/facts; never used to seed an Owner instance."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

from analysis_numeric_fixture import seed_numeric
from sqlalchemy.ext.asyncio import async_sessionmaker

from investment_os.application.analysis_decision_bridge import (
    DecisionGateFact,
    DecisionGateRule,
    DecisionQualification,
    StrategyDecisionRules,
    StrategyDecisionSnapshot,
)
from investment_os.application.analysis_risk_sizing import exact_number
from investment_os.application.analysis_runs import ANALYSIS_ROLES
from investment_os.application.investment_analysis import system_prompt
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.application.research import ResearchArtifactDTO
from investment_os.domain.agent import AgentRole
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.analysis_decision_models import (
    BridgeStrategyVersionRecord,
    DecisionQualificationFactRecord,
    DecisionQualificationRecord,
)
from investment_os.infrastructure.evidence_ingestion import SqlAlchemyEvidenceIngestor
from investment_os.infrastructure.persistence.models import EvidenceRecord


async def seed_qualification(
    engine,
    *,
    defect=None,
    existing_numeric=None,
    qualification_lifetime=timedelta(days=1),
    quality_threshold="1",
    strategy_human_approved=True,
    **numeric_options,
):
    ids, numeric = (
        existing_numeric
        if existing_numeric is not None
        else await seed_numeric(engine, **numeric_options)
    )
    now = datetime.now(UTC)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    rule_names = ("INVESTMENT_QUALITY", "TIMING", "PORTFOLIO_FIT")
    gate_evidence = await SqlAlchemyEvidenceIngestor(sessions, now=lambda: now).ingest(
        ResearchArtifactDTO(
            provider="SYNTHETIC",
            provider_ref=f"206-gate-facts-{uuid4()}",
            artifact_type="DERIVED_FEATURE",
            instrument_id=ids["instrument"],
            source_name="206明确合成规则资料",
            source_locator="synthetic://206/gate-facts",
            source_tier="PRIMARY",
            observed_at=UtcTimestamp(now - timedelta(minutes=1)),
            effective_at=UtcTimestamp(now - timedelta(minutes=1)),
            available_at=UtcTimestamp(now - timedelta(minutes=1)),
            expires_at=UtcTimestamp(now + timedelta(days=1)),
            source_schema_version="decision-gate-facts-1.0",
            payload={
                "schema_version": "decision-gate-facts-1.0",
                "facts": [{"metric": name, "value": "1"} for name in rule_names],
                "synthetic": True,
            },
        )
    )
    rules = StrategyDecisionRules(
        schema_version="strategy-decision-rules-1.0",
        allow_decision_proposals=True,
        simulation_only=True,
        portfolio_ids=(ids["portfolio"],),
        instrument_ids=(ids["instrument"],),
        valid_from=now - timedelta(days=1),
        valid_until=now + timedelta(days=1),
        review_after_seconds=3600,
        gates={
            name: (
                DecisionGateRule(
                    metric=name,
                    comparison="GTE",
                    threshold=quality_threshold if name == "INVESTMENT_QUALITY" else "1",
                ),
            )
            for name in rule_names
        },
    )
    strategy = StrategyDecisionSnapshot(
        strategy_version_id=uuid4(),
        version=1,
        status="ACTIVE",
        approved_by="explicit-synthetic-human" if strategy_human_approved else None,
        approved_by_actor="HUMAN" if strategy_human_approved else None,
        approved_at=now - timedelta(hours=1),
        prompt_bundle_hash=fingerprint(
            {
                role.value: sha256(
                    system_prompt(role, role in {AgentRole.CIO, AgentRole.PORTFOLIO}).encode()
                ).hexdigest()
                for role in ANALYSIS_ROLES
            }
        ),
        code_ref="synthetic-206-only",
        rules=rules,
        content_hash="0" * 64,
    )
    strategy = strategy.model_copy(update={"content_hash": strategy.expected_content_hash()})
    async with sessions() as session, session.begin():
        evidence = await session.get(EvidenceRecord, gate_evidence.evidence_id)
        assert evidence is not None
        qualification = DecisionQualification(
            schema_version="decision-qualification-1.0",
            qualification_id=uuid4(),
            portfolio_id=ids["portfolio"],
            instrument_id=ids["instrument"],
            policy_version_id=ids["policy_version"],
            numeric_snapshot_id=ids["snapshot"],
            portfolio_identity_hash=numeric.portfolio_identity_hash,
            strategy_version_id=strategy.strategy_version_id,
            strategy_content_hash=strategy.content_hash,
            source_kind="SYNTHETIC_FIXTURE",
            source_name="206明确合成资格",
            as_of=now,
            created_at=now,
            expires_at=now + qualification_lifetime,
            facts=tuple(
                DecisionGateFact(
                    metric=name,
                    value="2" if defect == "fabricated_value" else "1",
                    evidence_id=evidence.id,
                    evidence_content_hash="d" * 64
                    if defect == "evidence_hash"
                    else evidence.content_hash,
                )
                for name in rule_names
            ),
            content_hash="0" * 64,
        )
        qualification = qualification.model_copy(
            update={"content_hash": qualification.expected_content_hash()}
        )
        payload = qualification.model_dump(mode="json")
        if defect == "payload_hash":
            payload["source_name"] = "不是原来的资格来源"
        session.add(
            BridgeStrategyVersionRecord(
                id=strategy.strategy_version_id,
                version=1,
                status=strategy.status,
                rules_json=strategy.rules.model_dump(mode="json"),
                approved_by=strategy.approved_by,
                prompt_bundle_hash=strategy.prompt_bundle_hash,
                code_ref=strategy.code_ref,
                content_hash=strategy.content_hash,
                created_at=now,
                created_by="synthetic-206-only",
                correlation_id=uuid4(),
                metadata_json={
                    "approved_at": strategy.approved_at.isoformat(),
                    "approved_by_actor": strategy.approved_by_actor,
                },
            )
        )
        await session.flush()
        session.add(
            DecisionQualificationRecord(
                id=qualification.qualification_id,
                portfolio_id=qualification.portfolio_id,
                instrument_id=qualification.instrument_id,
                policy_version_id=qualification.policy_version_id,
                numeric_snapshot_id=qualification.numeric_snapshot_id,
                portfolio_identity_hash=qualification.portfolio_identity_hash,
                strategy_version_id=qualification.strategy_version_id,
                strategy_content_hash=qualification.strategy_content_hash,
                source_kind=qualification.source_kind,
                source_name="不匹配的来源名称" if defect == "header" else qualification.source_name,
                as_of=qualification.as_of,
                expires_at=qualification.expires_at,
                content_hash=qualification.content_hash,
                payload_json=payload,
                created_at=now,
                created_by="synthetic-206-only",
                correlation_id=uuid4(),
            )
        )
        await session.flush()
        session.add_all(
            [
                DecisionQualificationFactRecord(
                    qualification_id=qualification.qualification_id,
                    metric=fact.metric,
                    value=exact_number(fact.value),
                    evidence_id=fact.evidence_id,
                    evidence_content_hash=fact.evidence_content_hash,
                )
                for fact in qualification.facts
                if not (defect == "missing_relation" and fact.metric == "TIMING")
            ]
        )
    ids.update(
        qualification=qualification.qualification_id,
        strategy=strategy.strategy_version_id,
        gate_evidence=gate_evidence.evidence_id,
    )
    return ids, numeric, qualification, strategy
