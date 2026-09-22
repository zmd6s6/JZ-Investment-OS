"""Focused ORM mappings used by PR-02 repositories and reliable jobs.

The migration owns the complete core schema. These mappings intentionally cover only aggregates
whose persistence behavior is exercised before their later business workflows exist.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
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


class PositionLotRecord(AuditFieldsMixin, Base):
    """Immutable Core or Tactical cost lot; totals are never stored as a net-only lot."""

    __tablename__ = "position_lot"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    position_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    bucket: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PortfolioSnapshotRecord(AuditFieldsMixin, Base):
    """Immutable, content-addressed Portfolio state at one business time."""

    __tablename__ = "portfolio_snapshot"
    __table_args__ = (UniqueConstraint("portfolio_id", "as_of", "content_hash"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    portfolio_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    nav: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    gross_exposure: Mapped[Decimal] = mapped_column(Numeric(20, 12), nullable=False)
    net_exposure: Mapped[Decimal] = mapped_column(Numeric(20, 12), nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


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


class RiskAssessmentRecord(AuditFieldsMixin, Base):
    """Append-only evidence-backed hard/soft risk assessment."""

    __tablename__ = "risk_assessment"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    veto: Mapped[bool] = mapped_column(nullable=False)
    veto_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    hard_flags_json: Mapped[list[JSON]] = mapped_column(JSONB, nullable=False)
    soft_flags_json: Mapped[list[JSON]] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class RiskAssessmentEvidenceRecord(Base):
    __tablename__ = "risk_assessment_evidence"

    risk_assessment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("risk_assessment.id"), primary_key=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("evidence.id"), primary_key=True
    )


class PositionSizingRunRecord(AuditFieldsMixin, Base):
    """Append-only canonical PositionSizing request and deterministic output."""

    __tablename__ = "position_sizing_run"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    portfolio_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    instrument_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    decision_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    policy_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    input_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    formula_version: Mapped[str] = mapped_column(String(64), nullable=False)
    output_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)


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


class ConflictRecord(AuditFieldsMixin, Base):
    """An unresolved, deterministic committee disagreement kept append-only."""

    __tablename__ = "conflict_record"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    # The migration owns the foreign key to the complete committee-session table.
    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    conflict_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    opinion_ids: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[str | None] = mapped_column(Text)


class InvestmentDecisionRecord(AuditFieldsMixin, Base):
    __tablename__ = "investment_decision"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    instrument_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    portfolio_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    committee_session_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    thesis_version_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    policy_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    strategy_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    risk_assessment_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    position_sizing_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(20, 12), nullable=False)
    risk_intent: Mapped[str] = mapped_column(String(32), nullable=False)
    core_action: Mapped[str] = mapped_column(String(32), nullable=False)
    tactical_action: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    reasons_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    risks_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    watch_conditions_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    invalidation_conditions_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    next_review_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    position_before_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    position_after_proposed_json: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    unknowns_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    dissent_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    prompt_bundle_version: Mapped[str] = mapped_column(String(64), nullable=False)
    formula_version: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class InvestmentDecisionEvidenceRecord(Base):
    """Normalized immutable Evidence links for a Decision's audit snapshot."""

    __tablename__ = "investment_decision_evidence"

    investment_decision_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    evidence_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)


class DecisionApprovalRecord(AuditFieldsMixin, Base):
    """Append-only, attributed human action against one persisted Decision."""

    __tablename__ = "decision_approval"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    decision_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DecisionExecutionRecord(AuditFieldsMixin, Base):
    """Append-only paper/manual execution receipt; it never represents a broker order."""

    __tablename__ = "decision_execution"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    decision_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    approval_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    execution_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    filled_quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    avg_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    external_refs_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)


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


class ProductOnboardingStateRecord(Base):
    """Mutable, non-sensitive UI progress; it stores neither secrets nor investment data."""

    __tablename__ = "product_onboarding_state"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SystemSettingsRecord(Base):
    """Singleton product settings. It deliberately cannot enable automated trading."""

    __tablename__ = "system_settings"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    market_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    market_scopes_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    auto_trade: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ModelProviderProfileRecord(Base):
    """Provider metadata and an opaque credential reference, never a credential value."""

    __tablename__ = "model_provider_profile"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    provider_type: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    credential_ref: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), unique=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    pricing_version: Mapped[str | None] = mapped_column(String(64))
    pricing_currency: Mapped[str | None] = mapped_column(String(16))
    input_token_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    output_token_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    pricing_effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DataProviderProfileRecord(Base):
    """Authorized data-provider metadata and an opaque credential reference."""

    __tablename__ = "data_provider_profile"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    provider_type: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    credential_ref: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), unique=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RoleModelAssignmentRecord(Base):
    """One explicit enabled-model mapping per supported agent role or DEFAULT."""

    __tablename__ = "role_model_assignment"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    role: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    model_provider_profile_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("model_provider_profile.id"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LLMBudgetPolicyRecord(Base):
    """Singleton owner-configured hard limits; absent policy means no provider egress."""

    __tablename__ = "llm_budget_policy"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    task_token_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    daily_token_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    task_cost_limit: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    daily_cost_limit: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LLMBudgetTaskLedgerRecord(Base):
    __tablename__ = "llm_budget_task_ledger"

    task_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    reserved_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consumed_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_cost: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False, default=0)
    consumed_cost: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False, default=0)


class LLMBudgetDailyLedgerRecord(Base):
    __tablename__ = "llm_budget_daily_ledger"

    window_date: Mapped[date] = mapped_column(Date, primary_key=True)
    reserved_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consumed_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_cost: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False, default=0)
    consumed_cost: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False, default=0)


class LLMBudgetReservationRecord(Base):
    __tablename__ = "llm_budget_reservation"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    window_date: Mapped[date] = mapped_column(Date, nullable=False)
    pricing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    input_token_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    output_token_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    reserved_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_cost: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="RESERVED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LLMUsageRecord(Base):
    __tablename__ = "llm_usage"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    reservation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("llm_budget_reservation.id"), nullable=False, unique=True
    )
    task_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    window_date: Mapped[date] = mapped_column(Date, nullable=False)
    pricing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


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
