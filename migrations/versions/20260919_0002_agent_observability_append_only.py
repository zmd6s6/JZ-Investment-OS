"""Enforce append-only Agent and committee observability records.

Revision ID: 20260919_0002
Revises: 20260917_0001
Create Date: 2026-09-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260919_0002"
down_revision: str | None = "20260917_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPEND_ONLY_TABLES = (
    "agent_run",
    "committee_session",
    "committee_message",
    "conflict_record",
)


def upgrade() -> None:
    for table_name in _APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation()"
        )


def downgrade() -> None:
    for table_name in _APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER trg_{table_name}_append_only ON {table_name}")
