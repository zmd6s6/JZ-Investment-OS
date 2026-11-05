"""Persist scoped daily authorization, report and analysis lineage."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261104_0022"
down_revision = "20261104_0023"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "daily_configuration",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("enabled_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column("causation_id", sa.UUID(), nullable=True),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_configuration")),
    )
    op.create_table(
        "daily_authorization_revision",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("schedule_id", sa.UUID(), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("market", sa.String(length=32), nullable=False),
        sa.Column("portfolio_id", sa.UUID(), nullable=False),
        sa.Column("calendar_import_id", sa.UUID(), nullable=False),
        sa.Column("calendar_hash", sa.String(length=64), nullable=False),
        sa.Column("coverage_start", sa.Date(), nullable=False),
        sa.Column("coverage_end", sa.Date(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("prepared_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column("causation_id", sa.UUID(), nullable=True),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["calendar_import_id"],
            ["market_calendar_import.id"],
            name=op.f("fk_daily_authorization_revision_calendar_import_id_market_calendar_import"),
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolio.id"],
            name=op.f("fk_daily_authorization_revision_portfolio_id_portfolio"),
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"],
            ["daily_configuration.id"],
            name=op.f("fk_daily_authorization_revision_schedule_id_daily_configuration"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_authorization_revision")),
    )
    op.create_table(
        "daily_authorized_member",
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("instrument_id", sa.UUID(), nullable=False),
        sa.Column("in_portfolio", sa.Boolean(), nullable=False),
        sa.Column("in_watchlist", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instrument.id"],
            name=op.f("fk_daily_authorized_member_instrument_id_instrument"),
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["daily_authorization_revision.id"],
            name=op.f("fk_daily_authorized_member_revision_id_daily_authorization_revision"),
        ),
        sa.PrimaryKeyConstraint(
            "revision_id", "instrument_id", name=op.f("pk_daily_authorized_member")
        ),
    )
    op.create_table(
        "daily_execution",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_run_id", sa.UUID(), nullable=False),
        sa.Column("schedule_id", sa.UUID(), nullable=False),
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("authorization_version", sa.Integer(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("business_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("local_snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column("causation_id", sa.UUID(), nullable=True),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["daily_authorization_revision.id"],
            name=op.f("fk_daily_execution_revision_id_daily_authorization_revision"),
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"],
            ["daily_configuration.id"],
            name=op.f("fk_daily_execution_schedule_id_daily_configuration"),
        ),
        sa.ForeignKeyConstraint(
            ["task_run_id"], ["task_run.id"], name=op.f("fk_daily_execution_task_run_id_task_run")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_execution")),
        sa.UniqueConstraint(
            "schedule_id", "business_date", name=op.f("uq_daily_execution_schedule_id")
        ),
        sa.UniqueConstraint("task_run_id", name=op.f("uq_daily_execution_task_run_id")),
    )
    op.create_table(
        "daily_report_revision",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("execution_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usable_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("report_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column("causation_id", sa.UUID(), nullable=True),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["daily_execution.id"],
            name=op.f("fk_daily_report_revision_execution_id_daily_execution"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_report_revision")),
        sa.UniqueConstraint(
            "execution_id", "sequence", name=op.f("uq_daily_report_revision_execution_id")
        ),
    )
    op.create_table(
        "daily_report_evidence",
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("evidence_id", sa.UUID(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence.id"],
            name=op.f("fk_daily_report_evidence_evidence_id_evidence"),
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["daily_report_revision.id"],
            name=op.f("fk_daily_report_evidence_report_id_daily_report_revision"),
        ),
        sa.PrimaryKeyConstraint("report_id", "evidence_id", name=op.f("pk_daily_report_evidence")),
    )
    op.create_table(
        "daily_analysis_intent",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("execution_id", sa.UUID(), nullable=False),
        sa.Column("instrument_id", sa.UUID(), nullable=False),
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("command_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column("causation_id", sa.UUID(), nullable=True),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["daily_execution.id"],
            name=op.f("fk_daily_analysis_intent_execution_id_daily_execution"),
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instrument.id"],
            name=op.f("fk_daily_analysis_intent_instrument_id_instrument"),
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["daily_authorization_revision.id"],
            name=op.f("fk_daily_analysis_intent_revision_id_daily_authorization_revision"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_analysis_intent")),
        sa.UniqueConstraint(
            "execution_id", "instrument_id", name=op.f("uq_daily_analysis_intent_execution_id")
        ),
    )
    op.create_table(
        "daily_analysis_binding",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("analysis_run_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column("causation_id", sa.UUID(), nullable=True),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["analysis_run.id"],
            name=op.f("fk_daily_analysis_binding_analysis_run_id_analysis_run"),
        ),
        sa.ForeignKeyConstraint(
            ["id"],
            ["daily_analysis_intent.id"],
            name=op.f("fk_daily_analysis_binding_id_daily_analysis_intent"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_analysis_binding")),
        sa.UniqueConstraint(
            "analysis_run_id", name=op.f("uq_daily_analysis_binding_analysis_run_id")
        ),
    )
    op.create_table(
        "daily_report_analysis",
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("analysis_run_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["analysis_run.id"],
            name=op.f("fk_daily_report_analysis_analysis_run_id_analysis_run"),
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["daily_report_revision.id"],
            name=op.f("fk_daily_report_analysis_report_id_daily_report_revision"),
        ),
        sa.PrimaryKeyConstraint(
            "report_id", "analysis_run_id", name=op.f("pk_daily_report_analysis")
        ),
    )
    op.create_foreign_key(
        "daily_config_revision_fk",
        "daily_configuration",
        "daily_authorization_revision",
        ["revision_id"],
        ["id"],
        initially="DEFERRED",
        deferrable=True,
    )

    for table in (
        "daily_authorization_revision",
        "daily_authorized_member",
        "daily_execution",
        "daily_report_revision",
        "daily_report_evidence",
        "daily_analysis_intent",
        "daily_analysis_binding",
        "daily_report_analysis",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation()"
        )


def downgrade():
    connection = op.get_bind()
    for table in [
        "daily_configuration",
        "daily_authorization_revision",
        "daily_authorized_member",
        "daily_execution",
        "daily_report_revision",
        "daily_report_evidence",
        "daily_analysis_intent",
        "daily_analysis_binding",
        "daily_report_analysis",
    ]:
        if connection.execute(sa.text(f'SELECT EXISTS (SELECT 1 FROM "{table}" LIMIT 1)')).scalar():
            raise RuntimeError("daily history exists; retain tables and forward-fix")
    op.drop_constraint("daily_config_revision_fk", "daily_configuration", type_="foreignkey")
    op.drop_table("daily_report_analysis")
    op.drop_table("daily_analysis_binding")
    op.drop_table("daily_analysis_intent")
    op.drop_table("daily_report_evidence")
    op.drop_table("daily_report_revision")
    op.drop_table("daily_execution")
    op.drop_table("daily_authorized_member")
    op.drop_table("daily_authorization_revision")
    op.drop_table("daily_configuration")
