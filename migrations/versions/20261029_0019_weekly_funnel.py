"""Explicit zero-egress weekly local screening, preserving immutable history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "20261029_0019"
down_revision = "20261028_0018"
branch_labels = None
depends_on = None


def common():
    return (
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("correlation_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("causation_id", pg.UUID(as_uuid=True)),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("metadata_json", pg.JSONB(), nullable=False),
    )


def upgrade():
    op.create_table(
        "weekly_funnel_configuration",
        *common(),
        sa.Column("revision_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint("version >= 1", name="weekly_version_positive"),
    )
    op.create_table(
        "weekly_funnel_revision",
        *common(),
        sa.Column(
            "schedule_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("weekly_funnel_configuration.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("venue", sa.String(32), nullable=False),
        sa.Column(
            "calendar_import_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("market_calendar_import.id"),
            nullable=False,
        ),
        sa.Column("calendar_hash", sa.String(64), nullable=False),
        sa.Column("coverage_start", sa.Date(), nullable=False),
        sa.Column("coverage_end", sa.Date(), nullable=False),
        sa.Column("template_run_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("template_json", pg.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.CheckConstraint("venue IN ('SSE','SZSE')", name="weekly_venue"),
        sa.CheckConstraint(
            "EXTRACT(ISODOW FROM coverage_start)=1 "
            "AND EXTRACT(ISODOW FROM coverage_end)=7 "
            "AND coverage_end-coverage_start BETWEEN 6 AND 363",
            name="weekly_full_coverage",
        ),
    )
    op.create_foreign_key(
        "weekly_configuration_revision_fk",
        "weekly_funnel_configuration",
        "weekly_funnel_revision",
        ["revision_id"],
        ["id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "weekly_funnel_member",
        sa.Column(
            "revision_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("weekly_funnel_revision.id"),
            primary_key=True,
        ),
        sa.Column(
            "instrument_id", pg.UUID(as_uuid=True), sa.ForeignKey("instrument.id"), primary_key=True
        ),
    )
    op.create_table(
        "weekly_funnel_result",
        *common(),
        sa.Column(
            "task_run_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("task_run.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "revision_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("weekly_funnel_revision.id"),
            nullable=False,
        ),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(64)),
        sa.Column("funnel_run_id", pg.UUID(as_uuid=True)),
        sa.Column("funnel_event_id", pg.UUID(as_uuid=True), sa.ForeignKey("event_log.id")),
        sa.Column("candidate_count", sa.Integer()),
        sa.UniqueConstraint("revision_id", "week_start"),
        sa.CheckConstraint(
            "status IN ('COMPLETE','DEGRADED','EMPTY','SKIPPED_CLOSED')",
            name="weekly_result_status",
        ),
        sa.CheckConstraint(
            "(status='SKIPPED_CLOSED' AND funnel_run_id IS NULL "
            "AND funnel_event_id IS NULL AND candidate_count IS NULL) OR "
            "(status!='SKIPPED_CLOSED' AND funnel_run_id IS NOT NULL "
            "AND funnel_event_id IS NOT NULL AND candidate_count BETWEEN 0 AND 20)",
            name="weekly_result_link",
        ),
    )
    for table in ("weekly_funnel_revision", "weekly_funnel_member", "weekly_funnel_result"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation()"
        )


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM weekly_funnel_configuration)
      THEN RAISE EXCEPTION 'weekly history exists; preserve tables and forward-fix';
      END IF; END $$""")
    op.drop_constraint(
        "weekly_configuration_revision_fk", "weekly_funnel_configuration", type_="foreignkey"
    )
    for table in (
        "weekly_funnel_result",
        "weekly_funnel_member",
        "weekly_funnel_revision",
        "weekly_funnel_configuration",
    ):
        op.drop_table(table)
