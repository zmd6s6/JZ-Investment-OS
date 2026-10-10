"""PRODUCT-05: unique import idempotency claims for CSV batches.

Revision ID: 20260929_0013
Revises: 20260929_0012
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_0013"
down_revision: str | None = "20260929_0012"
branch_labels = None
depends_on = None

UUID = sa.Uuid()
TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "portfolio_import_claim",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("portfolio_id", UUID, nullable=False, index=True),
        sa.Column("import_hash", sa.String(64), nullable=False),
        sa.Column("audit_id", UUID, nullable=False),
        sa.Column("conflict_policy", sa.String(16), nullable=False),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="product_portfolio"),
        sa.UniqueConstraint("portfolio_id", "import_hash", name="uq_portfolio_import_hash"),
    )


def downgrade() -> None:
    op.drop_table("portfolio_import_claim")
