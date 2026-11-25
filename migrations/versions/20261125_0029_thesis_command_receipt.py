"""Add immutable human Thesis request receipts, retaining all historical versions."""

import sqlalchemy as sa
from alembic import op

revision = "20261125_0029"
down_revision = "20261117_0028"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE thesis_command_receipt (
      request_id uuid PRIMARY KEY,
      instrument_id uuid NOT NULL REFERENCES instrument(id),
      version_id uuid NOT NULL REFERENCES thesis_version(id),
      command_hash varchar(64) NOT NULL,
      result_json jsonb NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      created_by varchar(255) NOT NULL,
      correlation_id uuid NOT NULL,
      causation_id uuid,
      schema_version varchar(32) NOT NULL DEFAULT '1.0',
      metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb)""")
    op.execute("""CREATE TRIGGER trg_thesis_command_receipt_append_only
      BEFORE UPDATE OR DELETE ON thesis_command_receipt
      FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation()""")


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM thesis_command_receipt)"))
        .scalar()
    ):
        raise RuntimeError(
            "Thesis receipts exist; retain table and forward-fix; never delete audit history"
        )
    op.drop_table("thesis_command_receipt")
