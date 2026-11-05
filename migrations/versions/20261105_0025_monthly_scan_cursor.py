"""Persist the bounded monthly scanner position across Workers and restarts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261105_0025"
down_revision = "20261105_0024"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "monthly_scan_cursor",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=False),
        sa.Column("after_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("id = 1", name=op.f("ck_monthly_scan_cursor_singleton")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_monthly_scan_cursor")),
    )


def downgrade():
    # Runtime-only traversal position is reconstructible; no business history is removed.
    op.drop_table("monthly_scan_cursor")
