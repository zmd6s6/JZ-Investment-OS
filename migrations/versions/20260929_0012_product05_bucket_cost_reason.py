"""PRODUCT-05: per-bucket Core/Tactical cost and reason fields.

Revision ID: 20260929_0012
Revises: 20260929_0011
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_0012"
down_revision: str | None = "20260929_0011"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(38, 18)


def upgrade() -> None:
    op.add_column(
        "position",
        sa.Column("core_average_cost", MONEY, nullable=False, server_default="0"),
    )
    op.add_column(
        "position",
        sa.Column("tactical_average_cost", MONEY, nullable=False, server_default="0"),
    )
    op.add_column(
        "position",
        sa.Column("core_reason", sa.String(255), nullable=False, server_default=""),
    )
    op.add_column(
        "position",
        sa.Column("tactical_reason", sa.String(255), nullable=False, server_default=""),
    )
    op.add_column(
        "position",
        sa.Column("last_operation", sa.String(32), nullable=False, server_default="MANUAL"),
    )


def downgrade() -> None:
    op.drop_column("position", "last_operation")
    op.drop_column("position", "tactical_reason")
    op.drop_column("position", "core_reason")
    op.drop_column("position", "tactical_average_cost")
    op.drop_column("position", "core_average_cost")
