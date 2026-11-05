"""Immutable qualified Strategy facts and atomic Analysis-to-Decision linkage."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "20261104_0023"
# Serial integration, not numeric ordering: recheck the actual merged head before delivery.
down_revision = "20261029_0021"
branch_labels = None
depends_on = None


def audit():
    return (
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
        "analysis_decision_qualification",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        *audit(),
        sa.Column(
            "portfolio_id", pg.UUID(as_uuid=True), sa.ForeignKey("portfolio.id"), nullable=False
        ),
        sa.Column(
            "instrument_id", pg.UUID(as_uuid=True), sa.ForeignKey("instrument.id"), nullable=False
        ),
        sa.Column(
            "policy_version_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("investment_policy_version.id"),
            nullable=False,
        ),
        sa.Column(
            "numeric_snapshot_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("analysis_numeric_source.id"),
            nullable=False,
        ),
        sa.Column("portfolio_identity_hash", sa.String(64), nullable=False),
        sa.Column(
            "strategy_version_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("strategy_version.id"),
            nullable=False,
        ),
        sa.Column("strategy_content_hash", sa.String(64), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_name", sa.String(255), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", pg.JSONB(), nullable=False),
        sa.CheckConstraint("expires_at > as_of", name="decision_qualification_validity"),
        sa.CheckConstraint(
            "source_kind IN ('SYNTHETIC_FIXTURE','REFERENCE_ONLY')",
            name="decision_qualification_kind",
        ),
    )
    op.create_table(
        "analysis_decision_qualification_fact",
        sa.Column(
            "qualification_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("analysis_decision_qualification.id"),
            primary_key=True,
        ),
        sa.Column("metric", sa.String(80), primary_key=True),
        sa.Column("value", sa.Numeric(38, 18), nullable=False),
        sa.Column(
            "evidence_id", pg.UUID(as_uuid=True), sa.ForeignKey("evidence.id"), nullable=False
        ),
        sa.Column("evidence_content_hash", sa.String(64), nullable=False),
    )
    op.create_table(
        "analysis_decision_bridge",
        sa.Column(
            "run_id", pg.UUID(as_uuid=True), sa.ForeignKey("analysis_run.id"), nullable=False
        ),
        *audit(),
        sa.Column("request_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "qualification_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("analysis_decision_qualification.id"),
        ),
        sa.Column(
            "strategy_version_id", pg.UUID(as_uuid=True), sa.ForeignKey("strategy_version.id")
        ),
        sa.Column(
            "decision_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("investment_decision.id"),
            unique=True,
        ),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload_json", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("run_id", "revision"),
        sa.CheckConstraint("revision > 0", name="analysis_decision_bridge_revision"),
        sa.CheckConstraint(
            "status IN ('BLOCKED','PENDING_APPROVAL')", name="analysis_decision_bridge_status"
        ),
        sa.CheckConstraint(
            "(status='PENDING_APPROVAL') = (decision_id IS NOT NULL)",
            name="analysis_decision_bridge_identity",
        ),
        sa.CheckConstraint(
            "status <> 'PENDING_APPROVAL' OR "
            "(qualification_id IS NOT NULL AND strategy_version_id IS NOT NULL)",
            name="analysis_decision_bridge_qualified",
        ),
    )
    op.create_index(
        "uq_analysis_decision_per_run",
        "analysis_decision_bridge",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("decision_id IS NOT NULL"),
    )
    for table in (
        "analysis_decision_qualification",
        "analysis_decision_qualification_fact",
        "analysis_decision_bridge",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation()"
        )


def downgrade():
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM analysis_decision_qualification) "
        "OR EXISTS(SELECT 1 FROM analysis_decision_qualification_fact) "
        "OR EXISTS(SELECT 1 FROM analysis_decision_bridge) "
        "THEN RAISE EXCEPTION 'decision bridge history exists; preserve and forward-fix'; "
        "END IF; END $$"
    )
    for table in (
        "analysis_decision_bridge",
        "analysis_decision_qualification_fact",
        "analysis_decision_qualification",
    ):
        op.drop_table(table)
