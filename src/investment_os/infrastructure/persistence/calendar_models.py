"""Normalized immutable calendar imports/sessions and a versioned active configuration."""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from investment_os.infrastructure.persistence.base import Base
from investment_os.infrastructure.persistence.models import AuditFieldsMixin


class CalendarImportRecord(AuditFieldsMixin, Base):
    __tablename__ = "market_calendar_import"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    venue: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_version: Mapped[str] = mapped_column(String(200), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MarketSessionRecord(AuditFieldsMixin, Base):
    __tablename__ = "market_calendar_session"
    __table_args__ = (UniqueConstraint("import_id", "business_date"),)
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    import_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("market_calendar_import.id"), nullable=False, index=True
    )
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    close_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CalendarConfigurationRecord(AuditFieldsMixin, Base):
    __tablename__ = "market_calendar_configuration"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    venue: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    active_import_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("market_calendar_import.id"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
