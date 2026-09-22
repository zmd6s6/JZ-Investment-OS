"""Add fail-closed LLM pricing, budget reservations, and immutable usage.

Revision ID: 20260922_0007
Revises: 20260921_0006
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "20260922_0007"
down_revision: str | None = "20260921_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model_provider_profile", sa.Column("pricing_version", sa.String(64)))
    op.add_column("model_provider_profile", sa.Column("pricing_currency", sa.String(16)))
    op.add_column("model_provider_profile", sa.Column("input_token_price", sa.Numeric(38, 18)))
    op.add_column("model_provider_profile", sa.Column("output_token_price", sa.Numeric(38, 18)))
    op.add_column(
        "model_provider_profile", sa.Column("pricing_effective_at", sa.DateTime(timezone=True))
    )
    op.create_table(
        "llm_budget_policy",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("task_token_limit", sa.Integer, nullable=False),
        sa.Column("daily_token_limit", sa.Integer, nullable=False),
        sa.Column("task_cost_limit", sa.Numeric(38, 18), nullable=False),
        sa.Column("daily_cost_limit", sa.Numeric(38, 18), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    for name, key in (
        ("llm_budget_task_ledger", "task_id"),
        ("llm_budget_daily_ledger", "window_date"),
    ):
        op.create_table(
            name,
            sa.Column(key, UUID(as_uuid=True) if key == "task_id" else sa.Date, primary_key=True),
            sa.Column("reserved_tokens", sa.Integer, nullable=False, server_default="0"),
            sa.Column("consumed_tokens", sa.Integer, nullable=False, server_default="0"),
            sa.Column("reserved_cost", sa.Numeric(38, 18), nullable=False, server_default="0"),
            sa.Column("consumed_cost", sa.Numeric(38, 18), nullable=False, server_default="0"),
        )
    op.create_table(
        "llm_budget_reservation",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", UUID(as_uuid=True), nullable=False),
        sa.Column("window_date", sa.Date, nullable=False),
        sa.Column("pricing_version", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("input_token_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("output_token_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("reserved_input_tokens", sa.Integer, nullable=False),
        sa.Column("reserved_output_tokens", sa.Integer, nullable=False),
        sa.Column("reserved_cost", sa.Numeric(38, 18), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_llm_budget_reservation_task_id", "llm_budget_reservation", ["task_id"])
    op.create_table(
        "llm_usage",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "reservation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("llm_budget_reservation.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("task_id", UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", UUID(as_uuid=True), nullable=False),
        sa.Column("window_date", sa.Date, nullable=False),
        sa.Column("pricing_version", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("total_cost", sa.Numeric(38, 18), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute(
        "CREATE TRIGGER trg_llm_usage_append_only "
        "BEFORE UPDATE OR DELETE ON llm_usage "
        "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_llm_usage_append_only ON llm_usage")
    op.drop_table("llm_usage")
    op.drop_index("ix_llm_budget_reservation_task_id", table_name="llm_budget_reservation")
    op.drop_table("llm_budget_reservation")
    op.drop_table("llm_budget_daily_ledger")
    op.drop_table("llm_budget_task_ledger")
    op.drop_table("llm_budget_policy")
    for column in (
        "pricing_effective_at",
        "output_token_price",
        "input_token_price",
        "pricing_currency",
        "pricing_version",
    ):
        op.drop_column("model_provider_profile", column)
