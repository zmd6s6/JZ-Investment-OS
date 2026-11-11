"""Persist reconstructible daily configuration and report scan progress."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261111_0026"
down_revision = "20261105_0025"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "daily_scan_cursor",
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("after_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("kind IN ('CONFIGURATION', 'REPORT')", name="ck_daily_scan_kind"),
        sa.PrimaryKeyConstraint("kind", name="pk_daily_scan_cursor"),
    )


def downgrade():
    # Traversal alone is discarded. Daily history and authorization tables are untouched.
    op.drop_table("daily_scan_cursor")
