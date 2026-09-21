"""Persist non-sensitive PRODUCT-02 settings and provider configuration metadata.

Revision ID: 20260921_0006
Revises: 20260921_0005
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "20260921_0006"
down_revision: str | None = "20260921_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("market_timezone", sa.String(length=64), nullable=False),
        sa.Column(
            "market_scopes_json",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("auto_trade", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("auto_trade = false", name="system_settings_auto_trade_disabled"),
    )
    op.create_table(
        "model_provider_profile",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("provider_type", sa.String(length=128), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("credential_ref", UUID(as_uuid=True), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("credential_ref"),
        sa.CheckConstraint("timeout_seconds > 0", name="model_provider_profile_positive_timeout"),
        sa.CheckConstraint("max_tokens > 0", name="model_provider_profile_positive_max_tokens"),
    )
    op.create_table(
        "data_provider_profile",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("provider_type", sa.String(length=128), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("credential_ref", UUID(as_uuid=True), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("credential_ref"),
        sa.CheckConstraint("timeout_seconds > 0", name="data_provider_profile_positive_timeout"),
    )
    op.create_table(
        "role_model_assignment",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("model_provider_profile_id", UUID(as_uuid=True), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["model_provider_profile_id"], ["model_provider_profile.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role"),
    )


def downgrade() -> None:
    op.drop_table("role_model_assignment")
    op.drop_table("data_provider_profile")
    op.drop_table("model_provider_profile")
    op.drop_table("system_settings")
