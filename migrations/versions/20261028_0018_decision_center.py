"""Append-only human action revisions and complete manual execution facts.

Revision ID: 20261028_0018
Revises: 20261028_0016
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261028_0018"
down_revision = "20261028_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_center_action",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "decision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("investment_decision.id"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("resulting_state", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("command_hash", sa.String(64), nullable=False),
        sa.Column(
            "approval_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("decision_approval.id")
        ),
        sa.Column(
            "execution_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("decision_execution.id")
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("decision_id", "revision"),
        sa.CheckConstraint("revision > 1", name="center_revision_positive"),
        sa.CheckConstraint(
            "action IN ('APPROVE','REJECT','REVOKE','RECORD_EXECUTION')", name="center_action_valid"
        ),
        sa.CheckConstraint(
            "resulting_state IN "
            "('APPROVED','REJECTED','CANCELLED','PARTIALLY_EXECUTED','EXECUTED')",
            name="center_state_valid",
        ),
        sa.CheckConstraint(
            "length(trim(actor_id)) > 0 AND length(trim(comment)) > 0", name="center_actor_reason"
        ),
        sa.CheckConstraint(
            "(action = 'RECORD_EXECUTION') = (execution_id IS NOT NULL)",
            name="center_execution_link",
        ),
        sa.CheckConstraint("approval_id IS NOT NULL", name="center_approval_link"),
    )
    op.create_index(
        "ix_decision_center_action_decision_id", "decision_center_action", ["decision_id"]
    )
    op.create_table(
        "manual_execution_detail",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("decision_execution.id"),
            primary_key=True,
        ),
        sa.Column("fees", sa.Numeric(38, 18), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.CheckConstraint("fees >= 0", name="manual_fees_nonnegative"),
        sa.CheckConstraint("length(trim(note)) > 0", name="manual_note_present"),
    )
    for table in ("decision_center_action", "manual_execution_detail"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation()"
        )


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM decision_center_action)
      OR EXISTS (SELECT 1 FROM manual_execution_detail)
      THEN RAISE EXCEPTION 'human Decision history exists; preserve tables and forward-fix'; END IF;
    END $$""")
    for table in ("manual_execution_detail", "decision_center_action"):
        op.drop_table(table)
