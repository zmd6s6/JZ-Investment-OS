"""Frozen numeric sources and canonical Analysis Risk/Sizing lineage."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "20261029_0021"
down_revision = "20261029_0020"
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
        "analysis_numeric_source",
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
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_name", sa.String(255), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("portfolio_identity_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", pg.JSONB(), nullable=False),
        sa.CheckConstraint(
            "source_kind IN ('REFERENCE_ONLY','SYNTHETIC_FIXTURE')",
            name="numeric_source_qualification",
        ),
        sa.CheckConstraint("expires_at > as_of", name="numeric_source_time_order"),
    )
    op.create_table(
        "analysis_numeric_evidence",
        sa.Column(
            "snapshot_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("analysis_numeric_source.id"),
            primary_key=True,
        ),
        sa.Column("metric", sa.String(40), primary_key=True),
        sa.Column(
            "instrument_id", pg.UUID(as_uuid=True), sa.ForeignKey("instrument.id"), primary_key=True
        ),
        sa.Column(
            "evidence_id", pg.UUID(as_uuid=True), sa.ForeignKey("evidence.id"), nullable=False
        ),
    )
    op.create_table(
        "analysis_risk_result",
        *audit(),
        sa.Column(
            "run_id", pg.UUID(as_uuid=True), sa.ForeignKey("analysis_run.id"), primary_key=True
        ),
        sa.Column(
            "numeric_snapshot_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("analysis_numeric_source.id"),
        ),
        sa.Column("risk_assessment_id", pg.UUID(as_uuid=True), sa.ForeignKey("risk_assessment.id")),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payload_json", pg.JSONB(), nullable=False),
        sa.CheckConstraint(
            "status IN ('UNKNOWN','PASS','VETO')", name="analysis_numeric_risk_status"
        ),
        sa.CheckConstraint(
            "(status='UNKNOWN') = (risk_assessment_id IS NULL)",
            name="analysis_numeric_risk_identity",
        ),
    )
    op.create_table(
        "analysis_sizing_result",
        *audit(),
        sa.Column(
            "run_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("analysis_risk_result.run_id"),
            primary_key=True,
        ),
        sa.Column("sizing_run_id", pg.UUID(as_uuid=True), sa.ForeignKey("position_sizing_run.id")),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payload_json", pg.JSONB(), nullable=False),
        sa.CheckConstraint(
            "status IN ('BLOCKED','COMPUTED')", name="analysis_numeric_sizing_status"
        ),
        sa.CheckConstraint(
            "(status='BLOCKED') = (sizing_run_id IS NULL)", name="analysis_numeric_sizing_identity"
        ),
    )
    for table in (
        "analysis_numeric_source",
        "analysis_numeric_evidence",
        "analysis_risk_result",
        "analysis_sizing_result",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation()"
        )


def downgrade():
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM analysis_numeric_source) "
        "OR EXISTS(SELECT 1 FROM analysis_risk_result) "
        "OR EXISTS(SELECT 1 FROM analysis_sizing_result) "
        "THEN RAISE EXCEPTION 'analysis numeric/risk sizing history exists; "
        "preserve and forward-fix'; "
        "END IF; END $$"
    )
    for table in (
        "analysis_sizing_result",
        "analysis_risk_result",
        "analysis_numeric_evidence",
        "analysis_numeric_source",
    ):
        op.drop_table(table)
