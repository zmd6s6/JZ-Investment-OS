"""Daily pointers and append-only, normalized authorization/report/analysis lineage."""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from investment_os.infrastructure.persistence.base import Base
from investment_os.infrastructure.persistence.models import AuditFieldsMixin


class DailyConfigurationRecord(AuditFieldsMixin, Base):
    __tablename__ = "daily_configuration"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    revision_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "daily_authorization_revision.id",
            name="daily_config_revision_fk",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DailyAuthorizationRecord(AuditFieldsMixin, Base):
    __tablename__ = "daily_authorization_revision"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    schedule_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("daily_configuration.id"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    market: Mapped[str] = mapped_column(String(32), nullable=False)
    portfolio_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("portfolio.id"), nullable=False
    )
    calendar_import_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("market_calendar_import.id"), nullable=False
    )
    calendar_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    coverage_start: Mapped[date] = mapped_column(Date, nullable=False)
    coverage_end: Mapped[date] = mapped_column(Date, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False)
    prepared_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class DailyMemberRecord(Base):
    __tablename__ = "daily_authorized_member"
    revision_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("daily_authorization_revision.id"), primary_key=True
    )
    instrument_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("instrument.id"), primary_key=True
    )
    in_portfolio: Mapped[bool] = mapped_column(Boolean, nullable=False)
    in_watchlist: Mapped[bool] = mapped_column(Boolean, nullable=False)


class DailyExecutionRecord(AuditFieldsMixin, Base):
    __tablename__ = "daily_execution"
    __table_args__ = (UniqueConstraint("schedule_id", "business_date"),)
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    task_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("task_run.id"), nullable=False, unique=True
    )
    schedule_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("daily_configuration.id"), nullable=False
    )
    revision_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("daily_authorization_revision.id"), nullable=False
    )
    authorization_version: Mapped[int] = mapped_column(Integer, nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    local_snapshot_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class DailyReportRecord(AuditFieldsMixin, Base):
    __tablename__ = "daily_report_revision"
    __table_args__ = (UniqueConstraint("execution_id", "sequence"),)
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    execution_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("daily_execution.id"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usable_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    report_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class DailyReportEvidenceRecord(Base):
    __tablename__ = "daily_report_evidence"
    report_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("daily_report_revision.id"), primary_key=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("evidence.id"), primary_key=True
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)


class DailyAnalysisIntentRecord(AuditFieldsMixin, Base):
    __tablename__ = "daily_analysis_intent"
    __table_args__ = (UniqueConstraint("execution_id", "instrument_id"),)
    # id is the immutable AnalysisStart request_id, known before enqueue.
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    execution_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("daily_execution.id"), nullable=False
    )
    instrument_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("instrument.id"), nullable=False
    )
    revision_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("daily_authorization_revision.id"), nullable=False
    )
    command_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class DailyAnalysisBindingRecord(AuditFieldsMixin, Base):
    __tablename__ = "daily_analysis_binding"
    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("daily_analysis_intent.id"), primary_key=True
    )
    analysis_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analysis_run.id"), nullable=False, unique=True
    )


class DailyReportAnalysisRecord(Base):
    __tablename__ = "daily_report_analysis"
    report_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("daily_report_revision.id"), primary_key=True
    )
    analysis_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analysis_run.id"), primary_key=True
    )
