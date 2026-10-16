"""持久化分析任务与真实阶段事件。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261016_0017"
down_revision = "20261015_0016"
branch_labels = None
depends_on = None


def audit_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("causation_id", sa.Uuid()),
        sa.Column("schema_version", sa.String(32), nullable=False, server_default="1.0"),
        sa.Column("metadata_json", JSONB(), nullable=False, server_default="{}"),
    ]


def upgrade() -> None:
    op.create_table(
        "analysis_job",
        sa.Column("id", sa.Uuid(), sa.ForeignKey("analysis_run.id"), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("request_json", JSONB(), nullable=False),
        sa.Column("retry_of", sa.Uuid(), sa.ForeignKey("analysis_run.id")),
        sa.Column("worker_token", sa.Uuid()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
        *audit_columns(),
    )
    op.create_table(
        "analysis_progress",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("analysis_run.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        *audit_columns(),
        sa.UniqueConstraint("run_id", "sequence"),
        sa.CheckConstraint("sequence > 0", name="positive_sequence"),
    )
    op.create_index("ix_analysis_progress_run_id", "analysis_progress", ["run_id"])
    op.execute(
        "CREATE TRIGGER analysis_progress_append_only BEFORE UPDATE OR DELETE ON analysis_progress "
        "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation()"
    )
    op.execute("""CREATE FUNCTION preserve_analysis_job_input() RETURNS trigger AS $$
      BEGIN
        IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'analysis job input is immutable'; END IF;
        IF OLD.request_json IS DISTINCT FROM NEW.request_json OR
           OLD.request_hash IS DISTINCT FROM NEW.request_hash OR
           OLD.retry_of IS DISTINCT FROM NEW.retry_of OR OLD.id IS DISTINCT FROM NEW.id THEN
          RAISE EXCEPTION 'analysis job input is immutable';
        END IF;
        RETURN NEW;
      END; $$ LANGUAGE plpgsql""")
    op.execute(
        "CREATE TRIGGER analysis_job_input_immutable BEFORE UPDATE OR DELETE ON analysis_job "
        "FOR EACH ROW EXECUTE FUNCTION preserve_analysis_job_input()"
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM analysis_job)")):
        raise RuntimeError("分析任务历史非空, 禁止删除; 保留表并前向修复")
    op.drop_table("analysis_progress")
    op.drop_table("analysis_job")
    op.execute("DROP FUNCTION preserve_analysis_job_input()")
