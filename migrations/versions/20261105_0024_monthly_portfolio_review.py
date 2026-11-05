"""Persist independent monthly authorization and immutable portfolio review snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "20261105_0024"
down_revision = "20261104_0022"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """CREATE TABLE monthly_configuration (
                id UUID NOT NULL,
                revision_id UUID NOT NULL,
                version INTEGER NOT NULL,
                enabled BOOLEAN NOT NULL,
                revoked BOOLEAN NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
                created_by VARCHAR(255) NOT NULL,
                correlation_id UUID NOT NULL,
                causation_id UUID,
                schema_version VARCHAR(32) NOT NULL,
                metadata_json JSONB NOT NULL,
                CONSTRAINT pk_monthly_configuration PRIMARY KEY (id)
        )"""
    )
    op.execute(
        """CREATE TABLE monthly_authorization_revision (
                id UUID NOT NULL,
                schedule_id UUID NOT NULL,
                portfolio_id UUID NOT NULL,
                calendar_import_id UUID NOT NULL,
                market VARCHAR(32) NOT NULL,
                coverage_start DATE NOT NULL,
                coverage_end DATE NOT NULL,
                valid_from TIMESTAMP WITH TIME ZONE NOT NULL,
                valid_until TIMESTAMP WITH TIME ZONE NOT NULL,
                prepared_json JSONB NOT NULL,
                content_hash VARCHAR(64) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
                created_by VARCHAR(255) NOT NULL,
                correlation_id UUID NOT NULL,
                causation_id UUID,
                schema_version VARCHAR(32) NOT NULL,
                metadata_json JSONB NOT NULL,
                CONSTRAINT pk_monthly_authorization_revision PRIMARY KEY (id),
                CONSTRAINT fk_monthly_authorization_revision_schedule_id_monthly_c_0942 FOREIGN
        KEY(schedule_id) REFERENCES monthly_configuration (id),
                CONSTRAINT fk_monthly_authorization_revision_portfolio_id_portfolio FOREIGN
        KEY(portfolio_id) REFERENCES portfolio (id),
                CONSTRAINT fk_monthly_authorization_revision_calendar_import_id_ma_3452 FOREIGN
        KEY(calendar_import_id) REFERENCES market_calendar_import (id)
        )"""
    )
    op.execute(
        """CREATE TABLE monthly_authorized_member (
                revision_id UUID NOT NULL,
                instrument_id UUID NOT NULL,
                CONSTRAINT pk_monthly_authorized_member PRIMARY KEY (revision_id, instrument_id),
                CONSTRAINT fk_monthly_authorized_member_revision_id_monthly_author_7cca FOREIGN
        KEY(revision_id) REFERENCES monthly_authorization_revision (id),
                CONSTRAINT fk_monthly_authorized_member_instrument_id_instrument FOREIGN
        KEY(instrument_id) REFERENCES instrument (id)
        )"""
    )
    op.execute(
        """CREATE TABLE monthly_portfolio_report (
                id UUID NOT NULL,
                task_run_id UUID NOT NULL,
                schedule_id UUID NOT NULL,
                revision_id UUID NOT NULL,
                authorization_version INTEGER NOT NULL,
                period_start DATE NOT NULL,
                period_end DATE NOT NULL,
                business_as_of TIMESTAMP WITH TIME ZONE,
                knowledge_as_of TIMESTAMP WITH TIME ZONE NOT NULL,
                recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
                usable_until TIMESTAMP WITH TIME ZONE NOT NULL,
                baseline_report_id UUID,
                phase VARCHAR(32) NOT NULL,
                report_json JSONB NOT NULL,
                content_hash VARCHAR(64) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
                created_by VARCHAR(255) NOT NULL,
                correlation_id UUID NOT NULL,
                causation_id UUID,
                schema_version VARCHAR(32) NOT NULL,
                metadata_json JSONB NOT NULL,
                CONSTRAINT pk_monthly_portfolio_report PRIMARY KEY (id),
                CONSTRAINT uq_monthly_portfolio_report_schedule_id UNIQUE (schedule_id,
        period_start),
                CONSTRAINT uq_monthly_portfolio_report_task_run_id UNIQUE (task_run_id),
                CONSTRAINT fk_monthly_portfolio_report_task_run_id_task_run FOREIGN KEY(task_run_id)
        REFERENCES task_run (id),
                CONSTRAINT fk_monthly_portfolio_report_schedule_id_monthly_configuration FOREIGN
        KEY(schedule_id) REFERENCES monthly_configuration (id),
                CONSTRAINT fk_monthly_portfolio_report_revision_id_monthly_authori_730b FOREIGN
        KEY(revision_id) REFERENCES monthly_authorization_revision (id),
                CONSTRAINT fk_monthly_portfolio_report_baseline_report_id_monthly__9245 FOREIGN
        KEY(baseline_report_id) REFERENCES monthly_portfolio_report (id)
        )"""
    )
    op.execute(
        """CREATE TABLE monthly_report_evidence (
                report_id UUID NOT NULL,
                evidence_id UUID NOT NULL,
                CONSTRAINT pk_monthly_report_evidence PRIMARY KEY (report_id, evidence_id),
                CONSTRAINT fk_monthly_report_evidence_report_id_monthly_portfolio_report FOREIGN
        KEY(report_id) REFERENCES monthly_portfolio_report (id),
                CONSTRAINT fk_monthly_report_evidence_evidence_id_evidence FOREIGN KEY(evidence_id)
        REFERENCES evidence (id)
        )"""
    )
    op.execute(
        """CREATE TABLE monthly_report_reference (
                report_id UUID NOT NULL,
                kind VARCHAR(32) NOT NULL,
                record_id UUID NOT NULL,
                instrument_id UUID NOT NULL,
                content_hash VARCHAR(64) NOT NULL,
                thesis_id UUID,
                analysis_run_id UUID,
                risk_id UUID,
                decision_id UUID,
                CONSTRAINT pk_monthly_report_reference PRIMARY KEY (report_id, kind, record_id),
                CONSTRAINT ck_monthly_report_reference_monthly_exact_reference_kind CHECK
        (num_nonnulls(thesis_id, analysis_run_id, risk_id, decision_id)=1 AND COALESCE(record_id =
        CASE kind WHEN 'THESIS' THEN thesis_id WHEN 'ANALYSIS' THEN analysis_run_id WHEN 'RISK' THEN
        risk_id WHEN 'DECISION' THEN decision_id ELSE NULL END, FALSE)),
                CONSTRAINT fk_monthly_report_reference_report_id_monthly_portfolio_report FOREIGN
        KEY(report_id) REFERENCES monthly_portfolio_report (id),
                CONSTRAINT fk_monthly_report_reference_instrument_id_instrument FOREIGN
        KEY(instrument_id) REFERENCES instrument (id),
                CONSTRAINT fk_monthly_report_reference_thesis_id_thesis_version FOREIGN
        KEY(thesis_id) REFERENCES thesis_version (id),
                CONSTRAINT fk_monthly_report_reference_analysis_run_id_analysis_run FOREIGN
        KEY(analysis_run_id) REFERENCES analysis_run (id),
                CONSTRAINT fk_monthly_report_reference_risk_id_risk_assessment FOREIGN KEY(risk_id)
        REFERENCES risk_assessment (id),
                CONSTRAINT fk_monthly_report_reference_decision_id_investment_decision FOREIGN
        KEY(decision_id) REFERENCES investment_decision (id)
        )"""
    )
    op.execute(
        """ALTER TABLE monthly_configuration ADD CONSTRAINT monthly_config_revision_fk
        FOREIGN KEY(revision_id) REFERENCES monthly_authorization_revision (id)
        DEFERRABLE INITIALLY DEFERRED"""
    )
    for table in (
        "monthly_authorization_revision",
        "monthly_authorized_member",
        "monthly_portfolio_report",
        "monthly_report_evidence",
        "monthly_report_reference",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation()"
        )


def downgrade():
    connection = op.get_bind()
    for table in (
        "monthly_configuration",
        "monthly_authorization_revision",
        "monthly_authorized_member",
        "monthly_portfolio_report",
        "monthly_report_evidence",
        "monthly_report_reference",
    ):
        if connection.execute(sa.text(f'SELECT EXISTS (SELECT 1 FROM "{table}" LIMIT 1)')).scalar():
            raise RuntimeError("monthly history exists; retain tables and forward-fix")
    op.drop_constraint("monthly_config_revision_fk", "monthly_configuration", type_="foreignkey")
    op.drop_table("monthly_report_reference")
    op.drop_table("monthly_report_evidence")
    op.drop_table("monthly_portfolio_report")
    op.drop_table("monthly_authorized_member")
    op.drop_table("monthly_authorization_revision")
    op.drop_table("monthly_configuration")
