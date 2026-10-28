"""Append-only command receipts and complete manual fill facts, separate from snapshots."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from investment_os.infrastructure.persistence.base import Base


class DecisionCenterActionRecord(Base):
    __tablename__ = "decision_center_action"
    __table_args__ = (UniqueConstraint("decision_id", "revision"),)
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    decision_id: Mapped[UUID] = mapped_column(ForeignKey("investment_decision.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    resulting_state: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_id: Mapped[UUID | None] = mapped_column(ForeignKey("decision_approval.id"))
    execution_id: Mapped[UUID | None] = mapped_column(ForeignKey("decision_execution.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ManualExecutionDetailRecord(Base):
    __tablename__ = "manual_execution_detail"
    execution_id: Mapped[UUID] = mapped_column(
        "id", ForeignKey("decision_execution.id"), primary_key=True
    )
    fees: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
