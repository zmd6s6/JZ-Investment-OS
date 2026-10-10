"""Persist immutable PR-09 Outcome, Review, and human-review-only proposal fields.

Revision ID: 20260923_0009
Revises: 20260923_0008
Create Date: 2026-09-23

Existing append-only rows are deliberately not rewritten.  New application writes always
provide content hashes; nullable columns preserve forward-only migration safety for any
historical row created before this schema carried its canonical hash.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260923_0009"
down_revision: str | None = "20260923_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("decision_outcome", sa.Column("input_available_at", sa.DateTime(timezone=True)))
    op.add_column("decision_outcome", sa.Column("input_snapshot_hash", sa.String(64)))
    op.add_column("decision_outcome", sa.Column("content_hash", sa.String(64)))
    op.add_column("decision_review", sa.Column("content_hash", sa.String(64)))
    op.add_column("strategy_proposal", sa.Column("problem", sa.Text()))
    for column_name in (
        "training_window_start",
        "training_window_end",
        "validation_window_start",
        "validation_window_end",
    ):
        op.add_column("strategy_proposal", sa.Column(column_name, sa.DateTime(timezone=True)))
    op.add_column("strategy_proposal", sa.Column("backtest_result_json", JSONB))
    op.add_column("strategy_proposal", sa.Column("shadow_result_json", JSONB))
    op.add_column("strategy_proposal", sa.Column("rollback_conditions", JSONB))
    op.add_column("strategy_proposal", sa.Column("content_hash", sa.String(64)))
    op.execute(
        "CREATE TRIGGER trg_strategy_proposal_append_only "
        "BEFORE UPDATE OR DELETE ON strategy_proposal "
        "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_strategy_proposal_append_only ON strategy_proposal")
    for column_name in (
        "content_hash",
        "rollback_conditions",
        "shadow_result_json",
        "backtest_result_json",
        "validation_window_end",
        "validation_window_start",
        "training_window_end",
        "training_window_start",
        "problem",
    ):
        op.drop_column("strategy_proposal", column_name)
    op.drop_column("decision_review", "content_hash")
    for column_name in ("content_hash", "input_snapshot_hash", "input_available_at"):
        op.drop_column("decision_outcome", column_name)
