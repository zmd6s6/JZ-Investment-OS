"""Normalized weekly configuration pointer, immutable revisions/members and results."""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from investment_os.infrastructure.persistence.base import Base
from investment_os.infrastructure.persistence.models import AuditFieldsMixin


class WeeklyConfigurationRecord(AuditFieldsMixin, Base):
    __tablename__ = "weekly_funnel_configuration"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    revision_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "weekly_funnel_revision.id",
            name="weekly_configuration_revision_fk",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class WeeklyRevisionRecord(AuditFieldsMixin, Base):
    __tablename__ = "weekly_funnel_revision"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    schedule_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("weekly_funnel_configuration.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    venue: Mapped[str] = mapped_column(String(32), nullable=False)
    calendar_import_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("market_calendar_import.id"), nullable=False
    )
    calendar_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    coverage_start: Mapped[date] = mapped_column(Date, nullable=False)
    coverage_end: Mapped[date] = mapped_column(Date, nullable=False)
    template_run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    template_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class WeeklyMemberRecord(Base):
    __tablename__ = "weekly_funnel_member"
    revision_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("weekly_funnel_revision.id"), primary_key=True
    )
    instrument_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("instrument.id"), primary_key=True
    )


class WeeklyResultRecord(AuditFieldsMixin, Base):
    __tablename__ = "weekly_funnel_result"
    __table_args__ = (UniqueConstraint("revision_id", "week_start"),)
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    task_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("task_run.id"), nullable=False, unique=True
    )
    revision_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("weekly_funnel_revision.id"), nullable=False
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    funnel_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    funnel_event_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("event_log.id")
    )
    candidate_count: Mapped[int | None] = mapped_column(Integer)
