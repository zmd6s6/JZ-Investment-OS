"""Durable, fail-closed weekly local review authorization and immutable reports.

This migration does not enable any schedule or authorize external calls.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261115_0027"
down_revision = "20261111_0026"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "weekly_local_configuration",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("current_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint("version >= 0", name="weekly_local_version_nonnegative"),
        sa.CheckConstraint("NOT (enabled AND revoked)", name="weekly_local_revoked_not_enabled"),
    )
    op.create_table(
        "weekly_local_authorization",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("weekly_local_configuration.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("portfolio.id"), nullable=False),
        sa.Column("calendar_import_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("market_calendar_import.id"), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("coverage_start", sa.Date(), nullable=False),
        sa.Column("coverage_end", sa.Date(), nullable=False),
        sa.Column("authorization_json", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("schedule_id", "version", name="uq_weekly_local_authorization_version"),
        sa.UniqueConstraint("schedule_id", "id", name="uq_weekly_local_authorization_schedule_id"),
        sa.CheckConstraint("version > 0", name="weekly_local_revision_positive"),
        sa.CheckConstraint("valid_until > valid_from", name="weekly_local_valid_window"),
        sa.CheckConstraint("coverage_end >= coverage_start", name="weekly_local_coverage_window"),
        sa.CheckConstraint("EXTRACT(ISODOW FROM coverage_start) = 1", name="weekly_local_coverage_starts_monday"),
        sa.CheckConstraint("EXTRACT(ISODOW FROM coverage_end) = 7", name="weekly_local_coverage_ends_sunday"),
    )
    op.create_foreign_key(
        "fk_weekly_local_current_revision",
        "weekly_local_configuration",
        "weekly_local_authorization",
        ["id", "current_revision_id"],
        ["schedule_id", "id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "weekly_local_member",
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("weekly_local_authorization.id"), primary_key=True),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("instrument.id"), primary_key=True),
        sa.Column("membership", sa.String(16), primary_key=True),
        sa.CheckConstraint("membership IN ('PORTFOLIO','WATCHLIST')", name="weekly_local_membership_type"),
    )
    op.create_table(
        "weekly_local_report",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("weekly_local_configuration.id"), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["schedule_id", "revision_id"],
            ["weekly_local_authorization.schedule_id", "weekly_local_authorization.id"],
            name="fk_weekly_local_report_authorized_revision",
        ),
        sa.Column("task_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("task_run.id"), nullable=False, unique=True),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("knowledge_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("report_json", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("schedule_id", "week_start", name="uq_weekly_local_report_week"),
        sa.CheckConstraint("week_end = week_start + 6", name="weekly_local_complete_week"),
        sa.CheckConstraint("EXTRACT(ISODOW FROM week_start) = 1", name="weekly_local_report_starts_monday"),
    )
    op.create_index("ix_weekly_local_report_schedule_history", "weekly_local_report", ["schedule_id", "week_start"])
    op.create_table(
        "weekly_local_report_evidence",
        sa.Column("report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("weekly_local_report.id"), primary_key=True),
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("evidence.id"), primary_key=True),
    )
    # DB enforcement, not just ORM policy: no updates/deletes to historical facts.
    op.execute("""
        CREATE FUNCTION reject_weekly_local_history_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'weekly local history is append-only';
        END; $$;
    """)
    for table in ("weekly_local_authorization", "weekly_local_member",
                  "weekly_local_report", "weekly_local_report_evidence"):
        op.execute(f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_weekly_local_history_change()
        """)


def downgrade():
    # No destructive rollback of consent, report or provenance.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM weekly_local_authorization LIMIT 1)
             OR EXISTS (SELECT 1 FROM weekly_local_report LIMIT 1)
          THEN RAISE EXCEPTION 'weekly local history exists'; END IF;
        END $$;
    """)
    for table in ("weekly_local_report_evidence", "weekly_local_report",
                  "weekly_local_member", "weekly_local_authorization"):
        op.execute(f"DROP TRIGGER trg_{table}_immutable ON {table}")
    op.execute("DROP FUNCTION reject_weekly_local_history_change()")
    op.drop_table("weekly_local_report_evidence")
    op.drop_index("ix_weekly_local_report_schedule_history", table_name="weekly_local_report")
    op.drop_table("weekly_local_report")
    op.drop_table("weekly_local_member")
    op.drop_constraint("fk_weekly_local_current_revision", "weekly_local_configuration", type_="foreignkey")
    op.drop_table("weekly_local_authorization")
    op.drop_table("weekly_local_configuration")
