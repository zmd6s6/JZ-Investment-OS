"""Make PR-06 Risk and PositionSizing artifacts database-immutable.

Revision ID: 20260920_0002
Revises: 20260919_0002
Create Date: 2026-09-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260920_0002"
down_revision: str | None = "20260919_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table_name in ("risk_assessment", "position_sizing_run"):
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation()"
        )


def downgrade() -> None:
    for table_name in ("position_sizing_run", "risk_assessment"):
        op.execute(f"DROP TRIGGER trg_{table_name}_append_only ON {table_name}")
