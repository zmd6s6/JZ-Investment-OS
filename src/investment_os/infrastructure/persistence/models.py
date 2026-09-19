"""Focused ORM mappings used by PR-02 repositories and reliable jobs.

The migration owns the complete core schema. These mappings intentionally cover only aggregates
whose persistence behavior is exercised before their later business workflows exist.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from investment_os.infrastructure.persistence.base import Base

JSON = dict[str, Any]


class AuditFieldsMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    causation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0")
    metadata_json: Mapped[JSON] = mapped_column(JSONB, nullable=False, default=dict)


class InvestmentPolicyRecord(AuditFieldsMixin, Base):
    __tablename__ = "investment_policy"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_version_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class InvestmentPolicyVersionRecord(AuditFieldsMixin, Base):
    __tablename__ = "investment_policy_version"
    __table_args__ = (UniqueConstraint("policy_id", "version"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    policy_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("investment_policy.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    config_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class PositionRecord(AuditFieldsMixin, Base):
    __tablename__ = "position"
    __table_args__ = (UniqueConstraint("portfolio_id", "instrument_id"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    portfolio_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    instrument_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    core_quantity: Mapped[Decimal] = mapped_column(
        Numeric(38, 18), nullable=False, default=Decimal(0)
    )
    tactical_quantity: Mapped[Decimal] = mapped_column(
        Numeric(38, 18), nullable=False, default=Decimal(0)
    )
    avg_cost: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False, default=Decimal(0))
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(38, 18), nullable=False, default=Decimal(0)
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class InvestmentThesisRecord(AuditFieldsMixin, Base):
    __tablename__ = "investment_thesis"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    instrument_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_version_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ThesisVersionRecord(AuditFieldsMixin, Base):
    __tablename__ = "thesis_version"
    __table_args__ = (UniqueConstraint("thesis_id", "version"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    thesis_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("investment_thesis.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("thesis_version.id")
    )
    thesis_state: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    pillars_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    catalysts_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    risks_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    invalidation_conditions_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    monitoring_conditions_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    change_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ThesisVersionEvidenceRecord(Base):
    """Normalized immutable provenance links for a ThesisVersion."""

    __tablename__ = "thesis_version_evidence"

    thesis_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("thesis_version.id"),
        primary_key=True,
    )
    evidence_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("evidence.id"),
        primary_key=True,
    )


class EvidenceRecord(AuditFieldsMixin, Base):
    __tablename__ = "evidence"
    __table_args__ = (UniqueConstraint("source_name", "source_locator", "content_hash"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    instrument_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_locator: Mapped[str] = mapped_column(Text, nullable=False)
    source_tier: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quality_score: Mapped[Decimal] = mapped_column(Numeric(20, 12), nullable=False)
    freshness_status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    supersedes_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))


class ResearchArtifactRecord(AuditFieldsMixin, Base):
    __tablename__ = "research_artifact"
    __table_args__ = (UniqueConstraint("provider", "provider_ref", "content_hash"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_payload_ref: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_payload_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class FeatureSnapshotRecord(AuditFieldsMixin, Base):
    __tablename__ = "feature_snapshot"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    instrument_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String(64), nullable=False)
    values_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class AgentRunRecord(AuditFieldsMixin, Base):
    """Completed, immutable provenance for one bounded model execution."""

    __tablename__ = "agent_run"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_role: Mapped[str] = mapped_column(String(64), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(255), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    token_usage_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(255))


class AgentOpinionRecord(AuditFieldsMixin, Base):
    """Persisted structured opinion with payload and Evidence links kept separately immutable."""

    __tablename__ = "agent_opinion"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    # The migration owns foreign keys to tables not yet mapped by this focused ORM surface.
    agent_run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    instrument_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    stance: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(20, 12), nullable=False)
    time_horizon: Mapped[str] = mapped_column(String(32), nullable=False)
    observations_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    thesis_impacts_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    assumptions_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    risks_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    invalidation_conditions_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    unknowns_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class CommitteeSessionRecord(AuditFieldsMixin, Base):
    """A complete immutable record of a committee's finite two-round lifecycle."""

    __tablename__ = "committee_session"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    instrument_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    session_type: Mapped[str] = mapped_column(String(64), nullable=False)
    round_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CommitteeMessageRecord(AuditFieldsMixin, Base):
    """Append-only structured committee communication; raw provider text is not stored here."""

    __tablename__ = "committee_message"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_role: Mapped[str] = mapped_column(String(64), nullable=False)
    message_type: Mapped[str] = mapped_column(String(64), nullable=False)
    opinion_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    targets_opinion_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    payload_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)


class InvestmentDecisionRecord(AuditFieldsMixin, Base):
    __tablename__ = "investment_decision"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    instrument_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    portfolio_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    input_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class TaskRunRecord(AuditFieldsMixin, Base):
    __tablename__ = "task_run"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_json: Mapped[JSON | None] = mapped_column(JSONB)


class EventLogRecord(Base):
    __tablename__ = "event_log"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(255), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    payload_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    causation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0")
    metadata_json: Mapped[JSON] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OutboxEventRecord(AuditFieldsMixin, Base):
    __tablename__ = "outbox_event"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("event_log.id"), nullable=False, unique=True
    )
    topic: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    payload_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


class AuditLogRecord(Base):
    __tablename__ = "audit_log"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    operation: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    before_hash: Mapped[str | None] = mapped_column(String(64))
    after_hash: Mapped[str | None] = mapped_column(String(64))
    ip_or_runtime_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    causation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0")
    metadata_json: Mapped[JSON] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
