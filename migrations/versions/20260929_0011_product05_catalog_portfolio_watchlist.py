"""PRODUCT-05: instrument catalog metadata, portfolio bookkeeping, watchlist.

Revision ID: 20260929_0011
Revises: 20260923_0010
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_0011"
down_revision: str | None = "20260923_0010"
branch_labels = None
depends_on = None

UUID = sa.Uuid()
MONEY = sa.Numeric(38, 18)
TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column(
        "instrument", sa.Column("name", sa.String(255), nullable=False, server_default="")
    )
    op.add_column(
        "instrument", sa.Column("sector", sa.String(64), nullable=False, server_default="")
    )
    op.add_column("portfolio", sa.Column("name", sa.String(255), nullable=False, server_default=""))
    op.add_column(
        "portfolio",
        sa.Column("cash_balance", MONEY, nullable=False, server_default="0"),
    )
    # Manual P5 bookkeeping may create a portfolio before a human-approved policy row exists.
    # Policy linkage remains available; absence is explicit and must never invent a real policy.
    op.alter_column("portfolio", "policy_id", existing_type=UUID, nullable=True)

    op.create_table(
        "watchlist_item",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "instrument_id",
            UUID,
            sa.ForeignKey("instrument.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("added_at", TZ, nullable=False),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        sa.Column("correlation_id", UUID, nullable=False),
        sa.Column("causation_id", UUID),
        sa.Column("schema_version", sa.String(32), nullable=False, server_default="1.0"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False, server_default="system"),
    )
    op.create_index("ix_watchlist_item_instrument", "watchlist_item", ["instrument_id"])


def downgrade() -> None:
    op.alter_column("portfolio", "policy_id", existing_type=UUID, nullable=False)
    op.drop_index("ix_watchlist_item_instrument", table_name="watchlist_item")
    op.drop_table("watchlist_item")
    op.drop_column("portfolio", "cash_balance")
    op.drop_column("portfolio", "name")
    op.drop_column("instrument", "sector")
    op.drop_column("instrument", "name")
