"""Complete the governed StrategyProposal minimum fields without rewriting history.

Revision ID: 20260923_0010
Revises: 20260923_0009
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260923_0010"
down_revision: str | None = "20260923_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("strategy_proposal", sa.Column("evidence_ids", JSONB))
    op.add_column("strategy_proposal", sa.Column("baseline_metrics_json", JSONB))
    op.add_column("strategy_proposal", sa.Column("expected_side_effects", JSONB))
    op.add_column("strategy_proposal", sa.Column("human_approval_record_json", JSONB))


def downgrade() -> None:
    for column_name in (
        "human_approval_record_json",
        "expected_side_effects",
        "baseline_metrics_json",
        "evidence_ids",
    ):
        op.drop_column("strategy_proposal", column_name)
