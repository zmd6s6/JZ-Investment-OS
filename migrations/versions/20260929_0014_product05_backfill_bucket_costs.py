"""Forward-fix: backfill bucket average costs for rows written before 0013/0014.

Revision ID: 20260929_0014
Revises: 20260929_0013
Create Date: 2026-10-05
"""

from alembic import op

revision: str = "20260929_0014"
down_revision: str | None = "20260929_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Databases that ran 0012 before the backfill existed still have zeroed bucket costs.
    op.execute(
        """
        UPDATE position
        SET core_average_cost = avg_cost
        WHERE core_quantity <> 0 AND core_average_cost = 0
        """
    )
    op.execute(
        """
        UPDATE position
        SET tactical_average_cost = avg_cost
        WHERE tactical_quantity <> 0 AND tactical_average_cost = 0
        """
    )


def downgrade() -> None:
    # Data repair is intentionally not reversible.
    pass
