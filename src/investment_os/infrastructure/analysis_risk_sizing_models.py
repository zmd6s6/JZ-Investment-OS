"""Normalized, immutable numeric source identities and links to canonical risk/sizing records."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from investment_os.infrastructure.persistence.base import Base
from investment_os.infrastructure.persistence.models import AuditFieldsMixin


class AnalysisNumericSourceRecord(AuditFieldsMixin, Base):
    __tablename__ = "analysis_numeric_source"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    portfolio_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("portfolio.id"))
    instrument_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("instrument.id"))
    policy_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("investment_policy_version.id")
    )
    source_kind: Mapped[str] = mapped_column(String(32))
    source_name: Mapped[str] = mapped_column(String(255))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    portfolio_identity_hash: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict[str, object]] = mapped_column(JSONB)


class AnalysisNumericEvidenceRecord(Base):
    __tablename__ = "analysis_numeric_evidence"
    snapshot_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analysis_numeric_source.id"), primary_key=True
    )
    metric: Mapped[str] = mapped_column(String(40), primary_key=True)
    instrument_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("instrument.id"), primary_key=True
    )
    evidence_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("evidence.id"))


class AnalysisRiskResultRecord(AuditFieldsMixin, Base):
    __tablename__ = "analysis_risk_result"
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analysis_run.id"), primary_key=True
    )
    numeric_snapshot_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analysis_numeric_source.id")
    )
    risk_assessment_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("risk_assessment.id")
    )
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    payload_json: Mapped[dict[str, object]] = mapped_column(JSONB)


class AnalysisSizingResultRecord(AuditFieldsMixin, Base):
    __tablename__ = "analysis_sizing_result"
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analysis_risk_result.run_id"), primary_key=True
    )
    sizing_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("position_sizing_run.id")
    )
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    payload_json: Mapped[dict[str, object]] = mapped_column(JSONB)
