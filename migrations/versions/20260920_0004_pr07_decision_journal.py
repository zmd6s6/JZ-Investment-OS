"""Persist the complete immutable PR-07 Decision Journal snapshot.

Revision ID: 20260920_0004
Revises: 20260920_0003
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260920_0004"
down_revision: str | None = "20260920_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_VERSION = "unavailable-pre-pr07"
_LEGACY_HASH = "0" * 64


def upgrade() -> None:
    op.add_column(
        "investment_decision",
        sa.Column(
            "position_before_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )
    op.add_column(
        "investment_decision",
        sa.Column(
            "position_after_proposed_json",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "investment_decision",
        sa.Column("unknowns_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "investment_decision",
        sa.Column("dissent_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "investment_decision",
        sa.Column(
            "prompt_bundle_version",
            sa.String(64),
            nullable=False,
            server_default=sa.text(f"'{_LEGACY_VERSION}'"),
        ),
    )
    op.add_column(
        "investment_decision",
        sa.Column(
            "formula_version",
            sa.String(64),
            nullable=False,
            server_default=sa.text(f"'{_LEGACY_VERSION}'"),
        ),
    )
    op.add_column(
        "investment_decision",
        sa.Column(
            "content_hash",
            sa.String(64),
            nullable=False,
            server_default=sa.text(f"'{_LEGACY_HASH}'"),
        ),
    )


def downgrade() -> None:
    for column_name in (
        "content_hash",
        "formula_version",
        "prompt_bundle_version",
        "dissent_json",
        "unknowns_json",
        "position_after_proposed_json",
        "position_before_json",
    ):
        op.drop_column("investment_decision", column_name)
