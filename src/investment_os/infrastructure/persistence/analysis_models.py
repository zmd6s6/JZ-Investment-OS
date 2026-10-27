"""Normalized run state and append-only analysis inputs, steps and shadow artifacts."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from investment_os.infrastructure.persistence.base import Base
from investment_os.infrastructure.persistence.models import AuditFieldsMixin


class AnalysisRunRecord(AuditFieldsMixin, Base):
    __tablename__ = "analysis_run"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','SUCCEEDED','DEGRADED','FAILED','CANCELLED')",
            name="analysis_status",
        ),
    )
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    portfolio_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("portfolio.id"), nullable=False, index=True
    )
    instrument_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("instrument.id"), nullable=False, index=True
    )
    retry_of: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analysis_run.id")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    queued_input_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    input_hash: Mapped[str | None] = mapped_column(String(64))
    policy_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("investment_policy_version.id")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AnalysisInputRecord(AuditFieldsMixin, Base):
    __tablename__ = "analysis_input"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analysis_run.id"), nullable=False, unique=True
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class AnalysisEvidenceRecord(Base):
    __tablename__ = "analysis_run_evidence"
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analysis_run.id"), primary_key=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("evidence.id"), primary_key=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)


class AnalysisStepRecord(AuditFieldsMixin, Base):
    __tablename__ = "analysis_step"
    __table_args__ = (UniqueConstraint("run_id", "sequence"),)
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analysis_run.id"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(100))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class AnalysisRoleOutputRecord(AuditFieldsMixin, Base):
    __tablename__ = "analysis_role_output"
    __table_args__ = (UniqueConstraint("run_id", "role", "round_number", "schema_kind"),)
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analysis_run.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agent_run.id")
    )
    payload_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class AnalysisShadowDecisionRecord(AuditFieldsMixin, Base):
    __tablename__ = "analysis_shadow_decision"
    __table_args__ = (
        UniqueConstraint("id", "run_id"),
        CheckConstraint(
            "execution_allowed = false AND auto_trade = false AND action NOT IN ('BUY','ADD')",
            name="shadow_never_increases_exposure",
        ),
    )
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analysis_run.id"), nullable=False, unique=True
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_intent: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_gate: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("investment_policy_version.id")
    )
    thesis_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("thesis_version.id")
    )
    sizing_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("position_sizing_run.id")
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_trade: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class AnalysisShadowEvidenceRecord(Base):
    __tablename__ = "analysis_shadow_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["decision_id", "run_id"],
            ["analysis_shadow_decision.id", "analysis_shadow_decision.run_id"],
        ),
        ForeignKeyConstraint(
            ["run_id", "evidence_id"],
            ["analysis_run_evidence.run_id", "analysis_run_evidence.evidence_id"],
        ),
    )
    decision_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    evidence_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
