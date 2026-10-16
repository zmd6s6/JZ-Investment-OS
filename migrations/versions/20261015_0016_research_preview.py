"""P6 研究预览、原子确认与不可变分析输入快照。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261015_0016"
down_revision = "20261010_0015_analysis_run"
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
        "research_preview",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", JSONB(), nullable=False),
        *audit_columns(),
        sa.CheckConstraint("expires_at > created_at", name="preview_expiry_after_creation"),
    )
    op.create_table(
        "research_confirmation",
        sa.Column("id", sa.Uuid(), sa.ForeignKey("research_preview.id"), primary_key=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", JSONB(), nullable=False),
        *audit_columns(),
    )
    for table in ("research_preview", "research_confirmation"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation()"
        )
    op.execute("""CREATE FUNCTION preserve_analysis_input_snapshot() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.payload_json->'input_snapshot' IS NOT NULL THEN
              RAISE EXCEPTION 'analysis input snapshot is immutable';
            END IF;
            RETURN OLD;
          END IF;
          IF OLD.payload_json->'input_snapshot' IS NOT NULL AND
             (OLD.payload_json->'input_snapshot')::jsonb IS DISTINCT FROM
             (NEW.payload_json->'input_snapshot')::jsonb THEN
            RAISE EXCEPTION 'analysis input snapshot is immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql""")
    op.execute(
        "CREATE TRIGGER analysis_input_snapshot_immutable BEFORE UPDATE OR DELETE ON analysis_run "
        "FOR EACH ROW EXECUTE FUNCTION preserve_analysis_input_snapshot()"
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM research_preview) OR EXISTS "
            "(SELECT 1 FROM analysis_run WHERE payload_json->'input_snapshot' IS NOT NULL)"
        )
    ):
        raise RuntimeError("预览审计历史非空, 禁止删除; 请保留新增表并前向修复")
    op.execute("DROP TRIGGER analysis_input_snapshot_immutable ON analysis_run")
    op.execute("DROP FUNCTION preserve_analysis_input_snapshot()")
    op.drop_table("research_confirmation")
    op.drop_table("research_preview")
