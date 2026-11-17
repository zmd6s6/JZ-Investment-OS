"""Complete the existing weekly foundation without replacing historical records."""

import sqlalchemy as sa
from alembic import op

revision = "20261117_0028"
down_revision = "20261115_0027"
branch_labels = None
depends_on = None


def upgrade():
    for table in (
        "weekly_local_configuration",
        "weekly_local_authorization",
        "weekly_local_report",
    ):
        op.execute(f"""ALTER TABLE {table}
          ADD COLUMN created_at timestamptz NOT NULL DEFAULT now(),
          ADD COLUMN created_by varchar(255) NOT NULL DEFAULT 'weekly_legacy',
          ADD COLUMN correlation_id uuid NOT NULL DEFAULT gen_random_uuid(),
          ADD COLUMN causation_id uuid,
          ADD COLUMN schema_version varchar(32) NOT NULL DEFAULT '1.0',
          ADD COLUMN metadata_json jsonb NOT NULL DEFAULT '{{}}'::jsonb""")
    op.execute(
        "ALTER TABLE weekly_local_authorization ADD COLUMN market "
        "varchar(32) NOT NULL DEFAULT 'SSE'"
    )
    op.execute("""ALTER TABLE weekly_local_report
      ADD COLUMN authorization_version integer NOT NULL DEFAULT 0,
      ADD COLUMN business_as_of timestamptz,
      ADD COLUMN usable_until timestamptz NOT NULL DEFAULT '-infinity',
      ADD COLUMN baseline_report_id uuid REFERENCES weekly_local_report(id),
      ADD COLUMN phase varchar(32) NOT NULL DEFAULT 'LEGACY_UNVERIFIED'""")
    op.execute(
        "CREATE TABLE weekly_scan_cursor (id integer PRIMARY KEY CHECK(id=1), after_id uuid)"
    )
    op.execute("""CREATE TABLE weekly_calendar_day (
       revision_id uuid NOT NULL REFERENCES weekly_local_authorization(id),
       business_date date NOT NULL, state varchar(6) NOT NULL CHECK(state IN ('OPEN','CLOSED')),
       PRIMARY KEY(revision_id,business_date))""")
    op.execute("""CREATE TRIGGER trg_weekly_calendar_day_append_only
      BEFORE UPDATE OR DELETE ON weekly_calendar_day
      FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation()""")
    op.execute("""CREATE TABLE weekly_local_report_reference (
        report_id uuid NOT NULL REFERENCES weekly_local_report(id),
        kind varchar(32) NOT NULL, record_id uuid NOT NULL,
        instrument_id uuid NOT NULL REFERENCES instrument(id), content_hash varchar(64) NOT NULL,
        thesis_id uuid REFERENCES thesis_version(id),
        analysis_run_id uuid REFERENCES analysis_run(id),
        risk_id uuid REFERENCES risk_assessment(id),
        decision_id uuid REFERENCES investment_decision(id),
        PRIMARY KEY(report_id,kind,record_id),
        CHECK(num_nonnulls(thesis_id,analysis_run_id,risk_id,decision_id)=1 AND
        COALESCE(record_id=CASE kind
          WHEN 'THESIS' THEN thesis_id WHEN 'ANALYSIS' THEN analysis_run_id WHEN 'RISK' THEN risk_id
          WHEN 'DECISION' THEN decision_id ELSE NULL END,FALSE)))""")
    op.execute("""CREATE TRIGGER trg_weekly_reference_append_only
      BEFORE UPDATE OR DELETE ON weekly_local_report_reference
      FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation()""")


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM weekly_local_authorization) "
                "OR EXISTS(SELECT 1 FROM weekly_local_report)"
            )
        )
        .scalar()
    ):
        raise RuntimeError("weekly history exists; pause schedules, retain tables and forward-fix")
    op.drop_table("weekly_local_report_reference")
    op.drop_table("weekly_calendar_day")
    op.drop_table("weekly_scan_cursor")
    for column in (
        "phase",
        "baseline_report_id",
        "usable_until",
        "business_as_of",
        "authorization_version",
    ):
        op.drop_column("weekly_local_report", column)
    op.drop_column("weekly_local_authorization", "market")
    for table in (
        "weekly_local_configuration",
        "weekly_local_authorization",
        "weekly_local_report",
    ):
        for column in (
            "metadata_json",
            "schema_version",
            "causation_id",
            "correlation_id",
            "created_by",
            "created_at",
        ):
            op.drop_column(table, column)
