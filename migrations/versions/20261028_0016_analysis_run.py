"""Persist bounded AnalysisRun state and immutable shadow-analysis history.

Revision ID: 20261028_0016
Revises: 20261026_0015
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "20261028_0016"
down_revision = "20261026_0015"
branch_labels = None
depends_on = None


def audit() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("correlation_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("causation_id", pg.UUID(as_uuid=True)),
        sa.Column("schema_version", sa.String(32), nullable=False, server_default="1.0"),
        sa.Column(
            "metadata_json", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    ]


def ref(name: str, target: str, *, nullable: bool = True) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(name, pg.UUID(as_uuid=True), sa.ForeignKey(target), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "analysis_run",
        *audit(),
        sa.Column("request_id", pg.UUID(as_uuid=True), nullable=False, unique=True),
        ref("portfolio_id", "portfolio.id", nullable=False),
        ref("instrument_id", "instrument.id", nullable=False),
        ref("retry_of", "analysis_run.id"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("lease_id", pg.UUID(as_uuid=True)),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_code", sa.String(100)),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("queued_input_json", pg.JSONB(), nullable=False),
        sa.Column("input_hash", sa.String(64)),
        ref("policy_version_id", "investment_policy_version.id"),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('QUEUED','RUNNING','SUCCEEDED','DEGRADED','FAILED','CANCELLED')",
            name="analysis_status",
        ),
    )
    for column in ("portfolio_id", "instrument_id", "status"):
        op.create_index(f"ix_analysis_run_{column}", "analysis_run", [column])
    op.create_table(
        "analysis_input",
        *audit(),
        sa.Column(
            "run_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("analysis_run.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", pg.JSONB(), nullable=False),
    )
    op.create_table(
        "analysis_run_evidence",
        sa.Column(
            "run_id", pg.UUID(as_uuid=True), sa.ForeignKey("analysis_run.id"), primary_key=True
        ),
        sa.Column(
            "evidence_id", pg.UUID(as_uuid=True), sa.ForeignKey("evidence.id"), primary_key=True
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "analysis_step",
        *audit(),
        ref("run_id", "analysis_run.id", nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(100)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("run_id", "sequence"),
    )
    op.create_index("ix_analysis_step_run_id", "analysis_step", ["run_id"])
    op.create_table(
        "analysis_role_output",
        *audit(),
        ref("run_id", "analysis_run.id", nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("schema_kind", sa.String(64), nullable=False),
        ref("agent_run_id", "agent_run.id"),
        sa.Column("payload_json", pg.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("run_id", "role", "round_number", "schema_kind"),
    )
    op.create_index("ix_analysis_role_output_run_id", "analysis_role_output", ["run_id"])
    op.create_table(
        "analysis_shadow_decision",
        *audit(),
        sa.Column(
            "run_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("analysis_run.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("risk_intent", sa.String(32), nullable=False),
        sa.Column("risk_gate", sa.String(32), nullable=False),
        ref("policy_version_id", "investment_policy_version.id"),
        ref("thesis_version_id", "thesis_version.id"),
        ref("sizing_run_id", "position_sizing_run.id"),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("execution_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("auto_trade", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload_json", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("id", "run_id"),
        sa.CheckConstraint(
            "execution_allowed = false AND auto_trade = false AND action NOT IN ('BUY','ADD')",
            name="shadow_never_increases_exposure",
        ),
    )
    op.create_table(
        "analysis_shadow_evidence",
        sa.Column("decision_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("evidence_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", pg.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["decision_id", "run_id"],
            ["analysis_shadow_decision.id", "analysis_shadow_decision.run_id"],
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "evidence_id"],
            ["analysis_run_evidence.run_id", "analysis_run_evidence.evidence_id"],
        ),
    )
    for table in (
        "analysis_input",
        "analysis_run_evidence",
        "analysis_step",
        "analysis_role_output",
        "analysis_shadow_decision",
        "analysis_shadow_evidence",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation()"
        )
    op.execute("""CREATE FUNCTION guard_analysis_run() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'analysis run history cannot be deleted'; END IF;
        IF OLD.status IN ('SUCCEEDED','DEGRADED','FAILED','CANCELLED') THEN
            RAISE EXCEPTION 'terminal analysis is immutable'; END IF;
        IF OLD.request_id IS DISTINCT FROM NEW.request_id
            OR OLD.portfolio_id IS DISTINCT FROM NEW.portfolio_id
            OR OLD.instrument_id IS DISTINCT FROM NEW.instrument_id
            OR OLD.retry_of IS DISTINCT FROM NEW.retry_of
            OR OLD.request_hash IS DISTINCT FROM NEW.request_hash
            OR OLD.queued_input_json IS DISTINCT FROM NEW.queued_input_json
            OR OLD.policy_version_id IS DISTINCT FROM NEW.policy_version_id
            OR OLD.queued_at IS DISTINCT FROM NEW.queued_at THEN
            RAISE EXCEPTION 'analysis request is immutable'; END IF;
        IF OLD.input_hash IS NOT NULL AND OLD.input_hash IS DISTINCT FROM NEW.input_hash THEN
            RAISE EXCEPTION 'analysis input hash is immutable'; END IF;
        IF OLD.status = 'QUEUED' AND NEW.status NOT IN ('QUEUED','RUNNING','CANCELLED') THEN
            RAISE EXCEPTION 'analysis transition invalid'; END IF;
        IF OLD.status = 'RUNNING' AND NEW.status = 'QUEUED' THEN
            RAISE EXCEPTION 'analysis cannot silently replay'; END IF;
        RETURN NEW; END $$""")
    op.execute(
        "CREATE TRIGGER trg_analysis_run_guard BEFORE UPDATE OR DELETE ON analysis_run "
        "FOR EACH ROW EXECUTE FUNCTION guard_analysis_run()"
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM analysis_run) THEN "
        "RAISE EXCEPTION 'analysis history exists: use application rollback or forward fix'; "
        "END IF; END $$"
    )
    for table in (
        "analysis_shadow_evidence",
        "analysis_shadow_decision",
        "analysis_role_output",
        "analysis_step",
        "analysis_run_evidence",
        "analysis_input",
        "analysis_run",
    ):
        op.drop_table(table)
    op.execute("DROP FUNCTION guard_analysis_run()")
