"""Immutable source snapshots, normalized identity membership and exact run origins."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from investment_os.infrastructure.persistence.base import Base
from investment_os.infrastructure.persistence.models import AuditFieldsMixin


class UniverseSnapshotRecord(AuditFieldsMixin, Base):
    __tablename__ = "universe_snapshot"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("evidence.id"), nullable=False
    )
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    members_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)


class UniverseMemberRecord(Base):
    __tablename__ = "universe_snapshot_member"
    __table_args__ = (UniqueConstraint("snapshot_id", "market", "symbol"),)
    snapshot_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("universe_snapshot.id"), primary_key=True
    )
    instrument_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("instrument.id"), primary_key=True
    )
    market: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False)


class UniverseRunRecord(AuditFieldsMixin, Base):
    __tablename__ = "universe_funnel_origin"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    snapshot_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("universe_snapshot.id"), nullable=False
    )
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    run_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("event_log.id"), nullable=False, unique=True
    )
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
