"""PRODUCT-06: analysis_run persistence table."""

import sqlalchemy as sa
from alembic import op

revision: str = "20261010_0015_analysis_run"
down_revision: str | None = "20260929_0014"
branch_labels = None
depends_on = None

UUID = sa.Uuid()
TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "analysis_run",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("instrument_id", UUID, nullable=False, index=True),
        sa.Column("portfolio_id", UUID, nullable=False, index=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column("as_of", TZ, nullable=False),
        sa.Column("policy_version_label", sa.String(128), nullable=False, server_default="none"),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("failure_detail", sa.Text, nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("schema_version", sa.String(32), nullable=False, server_default="1.0"),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="product_ui"),
    )


def downgrade() -> None:
    op.drop_table("analysis_run")
