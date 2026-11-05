"""Read-only qualified Strategy/fact sources; provider text cannot grant permission."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.analysis_decision_bridge import (
    DecisionGateFact,
    DecisionQualification,
    StrategyDecisionRules,
    StrategyDecisionSnapshot,
)
from investment_os.application.analysis_risk_sizing import exact_number, utc_now
from investment_os.infrastructure.analysis_decision_models import (
    BridgeStrategyVersionRecord,
    DecisionQualificationFactRecord,
    DecisionQualificationRecord,
)
from investment_os.infrastructure.persistence.models import EvidenceRecord


class SqlDecisionQualifications:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        now: Callable[[], datetime] = utc_now,
    ):
        self._sessions, self._now = sessions, now

    async def read_strategy(
        self, session: AsyncSession, strategy_version_id: UUID
    ) -> StrategyDecisionSnapshot:
        row = await session.get(BridgeStrategyVersionRecord, strategy_version_id)
        if row is None:
            raise ValueError("DECISION_STRATEGY_VERSION_NOT_FOUND")
        try:
            return StrategyDecisionSnapshot(
                strategy_version_id=row.id,
                version=row.version,
                status=row.status,
                approved_by=row.approved_by,
                approved_by_actor=row.metadata_json.get("approved_by_actor"),
                approved_at=row.metadata_json.get("approved_at"),
                prompt_bundle_hash=row.prompt_bundle_hash,
                code_ref=row.code_ref,
                rules=StrategyDecisionRules.model_validate(row.rules_json),
                content_hash=row.content_hash,
            )
        except (ValueError, TypeError, KeyError):
            raise ValueError("DECISION_STRATEGY_VERSION_INVALID") from None

    async def read(
        self, session: AsyncSession, record: DecisionQualificationRecord
    ) -> DecisionQualification:
        try:
            value = DecisionQualification.model_validate(record.payload_json)
            if (
                record.content_hash != value.content_hash
                or value.content_hash != value.expected_content_hash()
            ):
                raise ValueError("DECISION_QUALIFICATION_HASH_MISMATCH")
            for name in (
                "portfolio_id",
                "instrument_id",
                "policy_version_id",
                "numeric_snapshot_id",
                "portfolio_identity_hash",
                "strategy_version_id",
                "strategy_content_hash",
                "source_kind",
                "source_name",
                "as_of",
                "created_at",
                "expires_at",
            ):
                if getattr(value, name) != getattr(record, name):
                    raise ValueError("DECISION_QUALIFICATION_HEADER_MISMATCH")
            if value.qualification_id != record.id:
                raise ValueError("DECISION_QUALIFICATION_IDENTITY_MISMATCH")
            links = (
                await session.scalars(
                    select(DecisionQualificationFactRecord).where(
                        DecisionQualificationFactRecord.qualification_id == record.id
                    )
                )
            ).all()
            expected_links = {
                (
                    fact.metric,
                    exact_number(fact.value),
                    fact.evidence_id,
                    fact.evidence_content_hash,
                )
                for fact in value.facts
            }
            if {
                (link.metric, link.value, link.evidence_id, link.evidence_content_hash)
                for link in links
            } != expected_links:
                raise ValueError("DECISION_GATE_FACT_RELATION_MISMATCH")
            identifiers = {fact.evidence_id for fact in value.facts}
            evidence = (
                await session.scalars(
                    select(EvidenceRecord).where(EvidenceRecord.id.in_(identifiers))
                )
            ).all()
            if {item.id for item in evidence} != identifiers:
                raise ValueError("DECISION_GATE_EVIDENCE_MISSING")
            facts_in_evidence: dict[tuple[UUID, str], DecisionGateFact] = {}
            for item in evidence:
                if (
                    item.instrument_id not in {None, value.instrument_id}
                    or item.freshness_status != "FRESH"
                    or item.quality_score <= 0
                    or item.expires_at is None
                    or self._now() >= item.expires_at
                    or max(item.observed_at, item.effective_at, item.available_at, item.ingested_at)
                    > value.as_of
                    or item.payload_json.get("schema_version") != "decision-gate-facts-1.0"
                    or not isinstance(item.payload_json.get("facts"), list)
                ):
                    raise ValueError("DECISION_GATE_EVIDENCE_INELIGIBLE")
                for raw in item.payload_json["facts"]:
                    fact = DecisionGateFact.model_validate(
                        {**raw, "evidence_id": item.id, "evidence_content_hash": item.content_hash}
                    )
                    key = (item.id, fact.metric)
                    if key in facts_in_evidence:
                        raise ValueError("DECISION_GATE_EVIDENCE_DUPLICATE_METRIC")
                    facts_in_evidence[key] = fact
            for fact in value.facts:
                actual = facts_in_evidence.get((fact.evidence_id, fact.metric))
                if (
                    actual is None
                    or actual.evidence_content_hash != fact.evidence_content_hash
                    or exact_number(actual.value) != exact_number(fact.value)
                ):
                    raise ValueError("DECISION_GATE_VALUE_NOT_IN_EVIDENCE")
            return value
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ValueError("DECISION_QUALIFICATION_INVALID") from None

    async def get(self, qualification_id: UUID) -> DecisionQualification:
        async with self._sessions() as session:
            row = await session.get(DecisionQualificationRecord, qualification_id)
            if row is None:
                raise ValueError("DECISION_QUALIFICATION_NOT_FOUND")
            return await self.read(session, row)

    async def list(
        self, portfolio_id: UUID, instrument_id: UUID
    ) -> tuple[DecisionQualification, ...]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(DecisionQualificationRecord)
                    .where(
                        DecisionQualificationRecord.portfolio_id == portfolio_id,
                        DecisionQualificationRecord.instrument_id == instrument_id,
                    )
                    .order_by(
                        DecisionQualificationRecord.created_at.desc(),
                        DecisionQualificationRecord.id,
                    )
                    .limit(30)
                )
            ).all()
            return tuple([await self.read(session, row) for row in rows])
