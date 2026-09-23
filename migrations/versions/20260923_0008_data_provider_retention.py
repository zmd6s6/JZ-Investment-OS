"""Add explicit retention configuration for data provider profiles.

Revision ID: 20260923_0008
Revises: 20260922_0007
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0008"
down_revision: str | None = "20260922_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "data_provider_profile",
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="365"),
    )
    op.create_check_constraint(
        "data_provider_profile_retention_range",
        "data_provider_profile",
        "retention_days >= 1 AND retention_days <= 3650",
    )


def downgrade() -> None:
    op.drop_constraint(
        "data_provider_profile_retention_range", "data_provider_profile", type_="check"
    )
    op.drop_column("data_provider_profile", "retention_days")
