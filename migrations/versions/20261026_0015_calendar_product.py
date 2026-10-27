"""Persist auditable calendar imports and explicit market sessions.

Revision ID: 20261026_0015
Revises: 20260929_0014
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261026_0015"
down_revision = "20260929_0014"
branch_labels = None
depends_on = None


def common() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("causation_id", postgresql.UUID(as_uuid=True)),
        sa.Column("schema_version", sa.String(32), nullable=False, server_default="1.0"),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "market_calendar_import",
        *common(),
        sa.Column("venue", sa.String(32), nullable=False),
        sa.Column("source_name", sa.String(200), nullable=False),
        sa.Column("source_version", sa.String(200), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("venue IN ('SSE','SZSE','US_EQUITIES')", name="calendar_import_venue"),
    )
    op.create_index("ix_market_calendar_import_venue", "market_calendar_import", ["venue"])
    op.create_table(
        "market_calendar_session",
        *common(),
        sa.Column(
            "import_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("market_calendar_import.id"),
            nullable=False,
        ),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("close_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("import_id", "business_date"),
    )
    op.create_index(
        "ix_market_calendar_session_import_id", "market_calendar_session", ["import_id"]
    )
    op.create_table(
        "market_calendar_configuration",
        *common(),
        sa.Column("venue", sa.String(32), nullable=False, unique=True),
        sa.Column(
            "active_import_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("market_calendar_import.id"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("version >= 1", name="calendar_configuration_version"),
    )
    for table in ("market_calendar_import", "market_calendar_session"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation()"
        )


def downgrade() -> None:
    # Never erase imported or scheduled history during a rollback; old app can retain these tables.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM market_calendar_import) THEN "
        "RAISE EXCEPTION 'calendar history exists: use application rollback or forward fix'; "
        "END IF; END $$"
    )
    op.drop_table("market_calendar_configuration")
    op.drop_table("market_calendar_session")
    op.drop_table("market_calendar_import")
