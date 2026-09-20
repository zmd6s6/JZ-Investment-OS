"""Make Core and Tactical position lots append-only.

Revision ID: 20260920_0003
Revises: 20260920_0002
Create Date: 2026-09-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260920_0003"
down_revision: str | None = "20260920_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TRIGGER trg_position_lot_append_only "
        "BEFORE UPDATE OR DELETE ON position_lot "
        "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_position_lot_append_only ON position_lot")
