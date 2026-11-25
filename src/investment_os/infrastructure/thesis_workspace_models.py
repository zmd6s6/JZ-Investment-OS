"""Immutable idempotency receipt for the human Thesis command."""

from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from investment_os.infrastructure.persistence.base import Base
from investment_os.infrastructure.persistence.models import AuditFieldsMixin


class ThesisCommandReceiptRecord(AuditFieldsMixin, Base):
    __tablename__ = "thesis_command_receipt"
    request_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    instrument_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("instrument.id"), nullable=False
    )
    version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("thesis_version.id"), nullable=False
    )
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
