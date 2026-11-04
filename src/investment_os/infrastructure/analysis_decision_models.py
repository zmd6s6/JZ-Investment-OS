"""Append-only qualification inputs and Analysis-to-Decision provenance, owned by MVP-206."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from investment_os.infrastructure.persistence.base import Base
from investment_os.infrastructure.persistence.models import AuditFieldsMixin


class BridgeStrategyVersionRecord(AuditFieldsMixin, Base):
    """Read existing immutable Strategy versions; this adapter has no activation operation."""

    __tablename__ = "strategy_version"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    rules_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    prompt_bundle_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class DecisionQualificationRecord(AuditFieldsMixin, Base):
    __tablename__ = "analysis_decision_qualification"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    portfolio_id: Mapped[UUID] = mapped_column(ForeignKey("portfolio.id"), nullable=False)
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instrument.id"), nullable=False)
    policy_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("investment_policy_version.id"), nullable=False
    )
    numeric_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_numeric_source.id"), nullable=False
    )
    portfolio_identity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("strategy_version.id"), nullable=False
    )
    strategy_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class DecisionQualificationFactRecord(Base):
    __tablename__ = "analysis_decision_qualification_fact"
    qualification_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_decision_qualification.id"), primary_key=True
    )
    metric: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    evidence_id: Mapped[UUID] = mapped_column(ForeignKey("evidence.id"), nullable=False)
    evidence_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class AnalysisDecisionBridgeRecord(AuditFieldsMixin, Base):
    __tablename__ = "analysis_decision_bridge"
    __table_args__ = (
        UniqueConstraint("run_id", "revision"),
        Index(
            "uq_analysis_decision_per_run",
            "run_id",
            unique=True,
            postgresql_where=text("decision_id IS NOT NULL"),
        ),
    )
    request_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("analysis_run.id"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    qualification_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("analysis_decision_qualification.id")
    )
    strategy_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("strategy_version.id"))
    decision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("investment_decision.id"), unique=True
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
