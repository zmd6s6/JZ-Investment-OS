"""PRODUCT-05: instrument catalog metadata, portfolio bookkeeping, watchlist."""

import sqlalchemy as sa
from alembic import op

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
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        sa.Column("updated_at", TZ, nullable=False),
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
