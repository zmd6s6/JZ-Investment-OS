"""Source-declared immutable universe intake and exact bounded funnel origin."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "20261029_0020"
down_revision = "20261029_0019"
branch_labels = None
depends_on = None


def common():
    return (
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("correlation_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("causation_id", pg.UUID(as_uuid=True)),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("metadata_json", pg.JSONB(), nullable=False),
    )


def upgrade():
    op.create_table(
        "universe_snapshot",
        *common(),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("source_json", pg.JSONB(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "evidence_id", pg.UUID(as_uuid=True), sa.ForeignKey("evidence.id"), nullable=False
        ),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("members_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("member_count BETWEEN 1 AND 1000", name="universe_upload_bound"),
    )
    op.create_table(
        "universe_snapshot_member",
        sa.Column(
            "snapshot_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("universe_snapshot.id"),
            primary_key=True,
        ),
        sa.Column(
            "instrument_id", pg.UUID(as_uuid=True), sa.ForeignKey("instrument.id"), primary_key=True
        ),
        sa.Column("market", sa.String(16), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("asset_type", sa.String(32), nullable=False),
        sa.UniqueConstraint("snapshot_id", "market", "symbol"),
        sa.CheckConstraint(
            "market IN ('SSE','SZSE') AND currency='CNY'", name="universe_supported_identity"
        ),
    )
    op.create_table(
        "universe_funnel_origin",
        *common(),
        sa.Column(
            "snapshot_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("universe_snapshot.id"),
            nullable=False,
        ),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("run_id", pg.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column(
            "run_event_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("event_log.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("request_hash", sa.String(64), nullable=False),
    )
    for table in ("universe_snapshot", "universe_snapshot_member", "universe_funnel_origin"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation()"
        )


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM universe_snapshot)
      THEN RAISE EXCEPTION 'universe history exists; preserve and forward-fix';
      END IF; END $$""")
    for table in ("universe_funnel_origin", "universe_snapshot_member", "universe_snapshot"):
        op.drop_table(table)
