"""Normalized weekly configuration, immutable authorization and report lineage."""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from investment_os.infrastructure.persistence.base import Base
from investment_os.infrastructure.persistence.models import AuditFieldsMixin


class WeeklyScanCursorRecord(Base):
    """Mutable traversal checkpoint; never an authorization or business fact."""

    __tablename__ = "weekly_scan_cursor"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    after_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)


class WeeklyConfigurationRecord(AuditFieldsMixin, Base):
    __tablename__ = "weekly_local_configuration"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    revision_id: Mapped[UUID] = mapped_column(
        "current_revision_id",
        PG_UUID(as_uuid=True),
        ForeignKey(
            "weekly_local_authorization.id",
            name="weekly_config_revision_fk",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class WeeklyAuthorizationRecord(AuditFieldsMixin, Base):
    __tablename__ = "weekly_local_authorization"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    schedule_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("weekly_local_configuration.id"), nullable=False
    )
    portfolio_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("portfolio.id"), nullable=False
    )
    calendar_import_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("market_calendar_import.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    market: Mapped[str] = mapped_column(String(32), nullable=False)
    coverage_start: Mapped[date] = mapped_column(Date, nullable=False)
    coverage_end: Mapped[date] = mapped_column(Date, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prepared_json: Mapped[dict[str, object]] = mapped_column(
        "authorization_json", JSONB, nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class WeeklyMemberRecord(Base):
    __tablename__ = "weekly_local_member"
    revision_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("weekly_local_authorization.id"), primary_key=True
    )
    instrument_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("instrument.id"), primary_key=True
    )

    membership: Mapped[str] = mapped_column(String(16), primary_key=True)


class WeeklyReportRecord(AuditFieldsMixin, Base):
    __tablename__ = "weekly_local_report"
    __table_args__ = (UniqueConstraint("schedule_id", "week_start"),)
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    task_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("task_run.id"), nullable=False, unique=True
    )
    schedule_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("weekly_local_configuration.id"), nullable=False
    )
    revision_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("weekly_local_authorization.id"), nullable=False
    )
    authorization_version: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[date] = mapped_column("week_start", Date, nullable=False)
    period_end: Mapped[date] = mapped_column("week_end", Date, nullable=False)
    business_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    knowledge_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usable_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    baseline_report_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("weekly_local_report.id")
    )
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    report_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class WeeklyReportEvidenceRecord(Base):
    __tablename__ = "weekly_local_report_evidence"
    report_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("weekly_local_report.id"), primary_key=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("evidence.id"), primary_key=True
    )


class WeeklyReportReferenceRecord(Base):
    __tablename__ = "weekly_local_report_reference"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(thesis_id, analysis_run_id, risk_id, decision_id)=1 AND "
            "COALESCE(record_id = CASE kind WHEN 'THESIS' THEN thesis_id "
            "WHEN 'ANALYSIS' THEN analysis_run_id WHEN 'RISK' THEN risk_id "
            "WHEN 'DECISION' THEN decision_id ELSE NULL END, FALSE)",
            name="weekly_exact_reference_kind",
        ),
    )
    report_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("weekly_local_report.id"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    instrument_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("instrument.id"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    thesis_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("thesis_version.id")
    )
    analysis_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analysis_run.id")
    )
    risk_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("risk_assessment.id")
    )
    decision_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("investment_decision.id")
    )


class WeeklyCalendarDayRecord(Base):
    __tablename__ = "weekly_calendar_day"
    revision_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("weekly_local_authorization.id"), primary_key=True
    )
    business_date: Mapped[date] = mapped_column(Date, primary_key=True)
    state: Mapped[str] = mapped_column(String(6), nullable=False)
