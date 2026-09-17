"""Create core persistence, audit, outbox, and reliable-job schema.

Revision ID: 20260917_0001
Revises: none
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260917_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
MONEY = sa.Numeric(38, 18)
RATIO = sa.Numeric(20, 12)
TZ = sa.DateTime(timezone=True)


def _id() -> sa.Column[object]:
    return sa.Column("id", UUID, primary_key=True)


def _audit_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("correlation_id", UUID, nullable=False),
        sa.Column("causation_id", UUID),
        sa.Column("schema_version", sa.String(32), nullable=False, server_default="1.0"),
        sa.Column("metadata_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    ]


def _evidence_link(table_name: str, owner_table: str, owner_column: str) -> None:
    op.create_table(
        table_name,
        sa.Column(
            owner_column,
            UUID,
            sa.ForeignKey(f"{owner_table}.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "evidence_id", UUID, sa.ForeignKey("evidence.id", ondelete="RESTRICT"), primary_key=True
        ),
    )


def upgrade() -> None:
    op.create_table(
        "instrument",
        _id(),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("exchange", sa.String(64), nullable=False),
        sa.Column("asset_type", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("lot_size", MONEY, nullable=False),
        sa.Column("sector_id", UUID),
        sa.Column("status", sa.String(32), nullable=False),
        *_audit_columns(),
        sa.UniqueConstraint("symbol", "exchange", name="uq_instrument_symbol_exchange"),
        sa.CheckConstraint("lot_size > 0", name="ck_instrument_lot_size_positive"),
    )

    op.create_table(
        "investment_policy",
        _id(),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_version_id", UUID),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_audit_columns(),
        sa.CheckConstraint("version > 0", name="ck_investment_policy_version_positive"),
    )
    op.create_table(
        "investment_policy_version",
        _id(),
        sa.Column(
            "policy_id",
            UUID,
            sa.ForeignKey("investment_policy.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config_json", JSONB, nullable=False),
        sa.Column("effective_from", TZ),
        sa.Column("approved_by", sa.String(255)),
        sa.Column("approved_at", TZ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        *_audit_columns(),
        sa.UniqueConstraint("policy_id", "version", name="uq_policy_version_number"),
        sa.CheckConstraint("version > 0", name="ck_policy_version_positive"),
    )
    op.create_foreign_key(
        "fk_policy_current_version",
        "investment_policy",
        "investment_policy_version",
        ["current_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "strategy_version",
        _id(),
        sa.Column("version", sa.Integer(), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("rules_json", JSONB, nullable=False),
        sa.Column("prompt_bundle_hash", sa.String(64), nullable=False),
        sa.Column("code_ref", sa.String(255), nullable=False),
        sa.Column("approved_by", sa.String(255)),
        sa.Column("content_hash", sa.String(64), nullable=False),
        *_audit_columns(),
    )
    op.create_table(
        "strategy_proposal",
        _id(),
        sa.Column("source_review_ids", JSONB, nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("proposed_change_json", JSONB, nullable=False),
        sa.Column("expected_effect", sa.Text(), nullable=False),
        sa.Column("risks", JSONB, nullable=False),
        sa.Column("backtest_result_id", UUID),
        sa.Column("shadow_result_id", UUID),
        sa.Column("status", sa.String(32), nullable=False),
        *_audit_columns(),
    )

    op.create_table(
        "portfolio",
        _id(),
        sa.Column("base_currency", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "policy_id",
            UUID,
            sa.ForeignKey("investment_policy.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *_audit_columns(),
    )
    op.create_table(
        "portfolio_snapshot",
        _id(),
        sa.Column(
            "portfolio_id", UUID, sa.ForeignKey("portfolio.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("as_of", TZ, nullable=False),
        sa.Column("cash", MONEY, nullable=False),
        sa.Column("nav", MONEY, nullable=False),
        sa.Column("gross_exposure", RATIO, nullable=False),
        sa.Column("net_exposure", RATIO, nullable=False),
        sa.Column("source", sa.String(255), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        *_audit_columns(),
        sa.UniqueConstraint(
            "portfolio_id", "as_of", "content_hash", name="uq_portfolio_snapshot_content"
        ),
    )
    op.create_table(
        "position",
        _id(),
        sa.Column(
            "portfolio_id", UUID, sa.ForeignKey("portfolio.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "instrument_id",
            UUID,
            sa.ForeignKey("instrument.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("core_quantity", MONEY, nullable=False, server_default="0"),
        sa.Column("tactical_quantity", MONEY, nullable=False, server_default="0"),
        sa.Column("avg_cost", MONEY, nullable=False, server_default="0"),
        sa.Column("realized_pnl", MONEY, nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_audit_columns(),
        sa.UniqueConstraint(
            "portfolio_id", "instrument_id", name="uq_position_portfolio_instrument"
        ),
        sa.CheckConstraint("core_quantity >= 0", name="ck_position_core_nonnegative"),
        sa.CheckConstraint("tactical_quantity >= 0", name="ck_position_tactical_nonnegative"),
        sa.CheckConstraint("version > 0", name="ck_position_version_positive"),
    )
    op.create_table(
        "position_lot",
        _id(),
        sa.Column(
            "position_id", UUID, sa.ForeignKey("position.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("bucket", sa.String(16), nullable=False),
        sa.Column("quantity", MONEY, nullable=False),
        sa.Column("cost", MONEY, nullable=False),
        sa.Column("opened_at", TZ, nullable=False),
        sa.Column("closed_at", TZ),
        *_audit_columns(),
        sa.CheckConstraint("bucket IN ('CORE', 'TACTICAL')", name="ck_position_lot_bucket"),
        sa.CheckConstraint("quantity > 0", name="ck_position_lot_quantity_positive"),
    )

    op.create_table(
        "investment_thesis",
        _id(),
        sa.Column(
            "instrument_id",
            UUID,
            sa.ForeignKey("instrument.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_version_id", UUID),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_audit_columns(),
    )
    op.create_table(
        "thesis_version",
        _id(),
        sa.Column(
            "thesis_id",
            UUID,
            sa.ForeignKey("investment_thesis.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "parent_version_id", UUID, sa.ForeignKey("thesis_version.id", ondelete="RESTRICT")
        ),
        sa.Column("thesis_state", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("pillars_json", JSONB, nullable=False),
        sa.Column("catalysts_json", JSONB, nullable=False),
        sa.Column("risks_json", JSONB, nullable=False),
        sa.Column("invalidation_conditions_json", JSONB, nullable=False),
        sa.Column("monitoring_conditions_json", JSONB, nullable=False),
        sa.Column("change_reason", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        *_audit_columns(),
        sa.UniqueConstraint("thesis_id", "version", name="uq_thesis_version_number"),
    )
    op.create_foreign_key(
        "fk_thesis_current_version",
        "investment_thesis",
        "thesis_version",
        ["current_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "evidence",
        _id(),
        sa.Column("instrument_id", UUID, sa.ForeignKey("instrument.id", ondelete="RESTRICT")),
        sa.Column("evidence_type", sa.String(64), nullable=False),
        sa.Column("source_name", sa.String(255), nullable=False),
        sa.Column("source_locator", sa.Text(), nullable=False),
        sa.Column("source_tier", sa.String(64), nullable=False),
        sa.Column("observed_at", TZ, nullable=False),
        sa.Column("effective_at", TZ, nullable=False),
        sa.Column("available_at", TZ, nullable=False),
        sa.Column("ingested_at", TZ, nullable=False),
        sa.Column("expires_at", TZ),
        sa.Column("quality_score", RATIO, nullable=False),
        sa.Column("freshness_status", sa.String(32), nullable=False),
        sa.Column("payload_json", JSONB, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("supersedes_id", UUID, sa.ForeignKey("evidence.id", ondelete="RESTRICT")),
        *_audit_columns(),
        sa.UniqueConstraint(
            "source_name", "source_locator", "content_hash", name="uq_evidence_source_content"
        ),
        sa.CheckConstraint(
            "quality_score >= 0 AND quality_score <= 1", name="ck_evidence_quality_range"
        ),
    )
    op.create_index("ix_evidence_available_at", "evidence", ["available_at"])
    op.create_table(
        "research_artifact",
        _id(),
        sa.Column("provider", sa.String(255), nullable=False),
        sa.Column("provider_ref", sa.String(255), nullable=False),
        sa.Column("artifact_type", sa.String(64), nullable=False),
        sa.Column("as_of", TZ, nullable=False),
        sa.Column("raw_payload_ref", sa.Text(), nullable=False),
        sa.Column("normalized_payload_json", JSONB, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        *_audit_columns(),
        sa.UniqueConstraint(
            "provider", "provider_ref", "content_hash", name="uq_research_artifact_content"
        ),
    )
    op.create_table(
        "feature_snapshot",
        _id(),
        sa.Column(
            "instrument_id",
            UUID,
            sa.ForeignKey("instrument.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("as_of", TZ, nullable=False),
        sa.Column("feature_set_version", sa.String(64), nullable=False),
        sa.Column("values_json", JSONB, nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        *_audit_columns(),
        sa.UniqueConstraint(
            "instrument_id",
            "as_of",
            "feature_set_version",
            "input_hash",
            name="uq_feature_snapshot_input",
        ),
    )

    op.create_table(
        "instrument_state",
        _id(),
        sa.Column(
            "instrument_id",
            UUID,
            sa.ForeignKey("instrument.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("lifecycle_state", sa.String(32), nullable=False),
        sa.Column("effective_at", TZ, nullable=False),
        sa.Column(
            "thesis_version_id", UUID, sa.ForeignKey("thesis_version.id", ondelete="RESTRICT")
        ),
        sa.Column("decision_id", UUID),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_audit_columns(),
    )
    op.create_table(
        "instrument_state_transition",
        _id(),
        sa.Column(
            "instrument_id",
            UUID,
            sa.ForeignKey("instrument.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("from_state", sa.String(32), nullable=False),
        sa.Column("to_state", sa.String(32), nullable=False),
        sa.Column("reason_codes", JSONB, nullable=False),
        sa.Column("authorized_by", sa.String(255), nullable=False),
        sa.Column("occurred_at", TZ, nullable=False),
        *_audit_columns(),
    )

    op.create_table(
        "agent_run",
        _id(),
        sa.Column("agent_role", sa.String(64), nullable=False),
        sa.Column("model_provider", sa.String(255), nullable=False),
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("input_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("started_at", TZ, nullable=False),
        sa.Column("ended_at", TZ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("token_usage_json", JSONB, nullable=False),
        sa.Column("error_code", sa.String(255)),
        *_audit_columns(),
    )
    op.create_table(
        "agent_opinion",
        _id(),
        sa.Column(
            "agent_run_id", UUID, sa.ForeignKey("agent_run.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "instrument_id",
            UUID,
            sa.ForeignKey("instrument.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("stance", sa.String(64), nullable=False),
        sa.Column("confidence", RATIO, nullable=False),
        sa.Column("time_horizon", sa.String(32), nullable=False),
        sa.Column("observations_json", JSONB, nullable=False),
        sa.Column("thesis_impacts_json", JSONB, nullable=False),
        sa.Column("assumptions_json", JSONB, nullable=False),
        sa.Column("risks_json", JSONB, nullable=False),
        sa.Column("invalidation_conditions_json", JSONB, nullable=False),
        sa.Column("unknowns_json", JSONB, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_agent_opinion_confidence_range"
        ),
    )
    op.create_table(
        "agent_performance",
        _id(),
        sa.Column("agent_role", sa.String(64), nullable=False),
        sa.Column("evaluation_window", sa.String(64), nullable=False),
        sa.Column("metric_version", sa.String(64), nullable=False),
        sa.Column("metrics_json", JSONB, nullable=False),
        *_audit_columns(),
    )

    op.create_table(
        "committee_session",
        _id(),
        sa.Column(
            "instrument_id",
            UUID,
            sa.ForeignKey("instrument.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("session_type", sa.String(64), nullable=False),
        sa.Column("round_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("input_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("started_at", TZ, nullable=False),
        sa.Column("completed_at", TZ),
        *_audit_columns(),
        sa.CheckConstraint(
            "round_count >= 0 AND round_count <= 2", name="ck_committee_round_limit"
        ),
    )
    op.create_table(
        "committee_message",
        _id(),
        sa.Column(
            "session_id",
            UUID,
            sa.ForeignKey("committee_session.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("agent_role", sa.String(64), nullable=False),
        sa.Column("message_type", sa.String(64), nullable=False),
        sa.Column("opinion_id", UUID, sa.ForeignKey("agent_opinion.id", ondelete="RESTRICT")),
        sa.Column(
            "targets_opinion_id", UUID, sa.ForeignKey("agent_opinion.id", ondelete="RESTRICT")
        ),
        sa.Column("payload_json", JSONB, nullable=False),
        *_audit_columns(),
        sa.CheckConstraint("round_number IN (1, 2)", name="ck_committee_message_round"),
    )
    op.create_table(
        "conflict_record",
        _id(),
        sa.Column(
            "session_id",
            UUID,
            sa.ForeignKey("committee_session.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("conflict_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("opinion_ids", JSONB, nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("resolution", sa.Text()),
        *_audit_columns(),
    )

    op.create_table(
        "risk_snapshot",
        _id(),
        sa.Column(
            "portfolio_id", UUID, sa.ForeignKey("portfolio.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("instrument_id", UUID, sa.ForeignKey("instrument.id", ondelete="RESTRICT")),
        sa.Column("as_of", TZ, nullable=False),
        sa.Column(
            "policy_version_id",
            UUID,
            sa.ForeignKey("investment_policy_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("metrics_json", JSONB, nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        *_audit_columns(),
    )
    op.create_table(
        "risk_assessment",
        _id(),
        sa.Column(
            "session_id",
            UUID,
            sa.ForeignKey("committee_session.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("veto", sa.Boolean(), nullable=False),
        sa.Column("veto_codes", JSONB, nullable=False),
        sa.Column("hard_flags_json", JSONB, nullable=False),
        sa.Column("soft_flags_json", JSONB, nullable=False),
        sa.Column("expires_at", TZ, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        *_audit_columns(),
    )
    op.create_table(
        "position_sizing_run",
        _id(),
        sa.Column(
            "portfolio_id", UUID, sa.ForeignKey("portfolio.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "instrument_id",
            UUID,
            sa.ForeignKey("instrument.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("decision_id", UUID),
        sa.Column(
            "policy_version_id",
            UUID,
            sa.ForeignKey("investment_policy_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("input_json", JSONB, nullable=False),
        sa.Column("formula_version", sa.String(64), nullable=False),
        sa.Column("output_json", JSONB, nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        *_audit_columns(),
    )

    op.create_table(
        "investment_decision",
        _id(),
        sa.Column(
            "instrument_id",
            UUID,
            sa.ForeignKey("instrument.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "portfolio_id", UUID, sa.ForeignKey("portfolio.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "committee_session_id", UUID, sa.ForeignKey("committee_session.id", ondelete="RESTRICT")
        ),
        sa.Column(
            "thesis_version_id", UUID, sa.ForeignKey("thesis_version.id", ondelete="RESTRICT")
        ),
        sa.Column(
            "policy_version_id",
            UUID,
            sa.ForeignKey("investment_policy_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "strategy_version_id",
            UUID,
            sa.ForeignKey("strategy_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "risk_assessment_id", UUID, sa.ForeignKey("risk_assessment.id", ondelete="RESTRICT")
        ),
        sa.Column(
            "position_sizing_run_id",
            UUID,
            sa.ForeignKey("position_sizing_run.id", ondelete="RESTRICT"),
        ),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("confidence", RATIO, nullable=False),
        sa.Column("risk_intent", sa.String(32), nullable=False),
        sa.Column("core_action", sa.String(32), nullable=False),
        sa.Column("tactical_action", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("reasons_json", JSONB, nullable=False),
        sa.Column("risks_json", JSONB, nullable=False),
        sa.Column("watch_conditions_json", JSONB, nullable=False),
        sa.Column("invalidation_conditions_json", JSONB, nullable=False),
        sa.Column("next_review_at", TZ, nullable=False),
        sa.Column("input_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_audit_columns(),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_decision_confidence_range"
        ),
    )
    op.create_foreign_key(
        "fk_sizing_decision",
        "position_sizing_run",
        "investment_decision",
        ["decision_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_instrument_state_decision",
        "instrument_state",
        "investment_decision",
        ["decision_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "decision_approval",
        _id(),
        sa.Column(
            "decision_id",
            UUID,
            sa.ForeignKey("investment_decision.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("expires_at", TZ),
        *_audit_columns(),
        sa.CheckConstraint(
            "action IN ('APPROVE', 'REJECT', 'REVOKE')", name="ck_decision_approval_action"
        ),
    )
    op.create_table(
        "decision_execution",
        _id(),
        sa.Column(
            "decision_id",
            UUID,
            sa.ForeignKey("investment_decision.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "approval_id",
            UUID,
            sa.ForeignKey("decision_approval.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("execution_mode", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("requested_quantity", MONEY, nullable=False),
        sa.Column("filled_quantity", MONEY, nullable=False, server_default="0"),
        sa.Column("avg_price", MONEY),
        sa.Column("external_refs_json", JSONB, nullable=False),
        *_audit_columns(),
    )
    op.create_table(
        "trade_record",
        _id(),
        sa.Column(
            "decision_id",
            UUID,
            sa.ForeignKey("investment_decision.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "approval_id",
            UUID,
            sa.ForeignKey("decision_approval.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("external_order_id", sa.String(255)),
        sa.Column("side", sa.String(16), nullable=False),
        sa.Column("quantity", MONEY, nullable=False),
        sa.Column("price", MONEY, nullable=False),
        sa.Column("fees", MONEY, nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("executed_at", TZ, nullable=False),
        sa.Column("source", sa.String(255), nullable=False),
        *_audit_columns(),
    )
    op.create_table(
        "decision_outcome",
        _id(),
        sa.Column(
            "decision_id",
            UUID,
            sa.ForeignKey("investment_decision.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("horizon", sa.String(64), nullable=False),
        sa.Column("evaluation_due_at", TZ, nullable=False),
        sa.Column("evaluated_at", TZ),
        sa.Column("market_context_json", JSONB, nullable=False),
        sa.Column("returns_json", JSONB, nullable=False),
        sa.Column("drawdown_json", JSONB, nullable=False),
        sa.Column("thesis_result", sa.String(64)),
        sa.Column("action_quality", sa.String(64)),
        sa.Column("data_version", sa.String(64), nullable=False),
        *_audit_columns(),
        sa.UniqueConstraint(
            "decision_id", "horizon", "data_version", name="uq_decision_outcome_horizon"
        ),
    )
    op.create_table(
        "decision_review",
        _id(),
        sa.Column(
            "decision_id",
            UUID,
            sa.ForeignKey("investment_decision.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "outcome_id",
            UUID,
            sa.ForeignKey("decision_outcome.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("review_type", sa.String(64), nullable=False),
        sa.Column("attribution_json", JSONB, nullable=False),
        sa.Column("what_was_right", sa.Text(), nullable=False),
        sa.Column("what_was_wrong", sa.Text(), nullable=False),
        sa.Column("unknowns", JSONB, nullable=False),
        sa.Column("proposal_ids", JSONB, nullable=False),
        *_audit_columns(),
    )

    op.create_table(
        "task_run",
        _id(),
        sa.Column("task_name", sa.String(255), nullable=False),
        sa.Column("scheduled_for", TZ, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("started_at", TZ, nullable=False),
        sa.Column("finished_at", TZ),
        sa.Column("error_json", JSONB),
        *_audit_columns(),
        sa.CheckConstraint("attempt > 0", name="ck_task_run_attempt_positive"),
    )
    op.create_table(
        "event_log",
        _id(),
        sa.Column("event_type", sa.String(255), nullable=False),
        sa.Column("aggregate_type", sa.String(255), nullable=False),
        sa.Column("aggregate_id", UUID, nullable=False),
        sa.Column("payload_json", JSONB, nullable=False),
        sa.Column("occurred_at", TZ, nullable=False),
        *_audit_columns(),
    )
    op.create_table(
        "outbox_event",
        _id(),
        sa.Column(
            "event_id",
            UUID,
            sa.ForeignKey("event_log.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("topic", sa.String(255), nullable=False),
        sa.Column("payload_json", JSONB, nullable=False),
        sa.Column("published_at", TZ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        *_audit_columns(),
        sa.CheckConstraint("attempts >= 0", name="ck_outbox_attempts_nonnegative"),
    )
    op.create_table(
        "audit_log",
        _id(),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("operation", sa.String(255), nullable=False),
        sa.Column("entity_type", sa.String(255), nullable=False),
        sa.Column("entity_id", UUID, nullable=False),
        sa.Column("before_hash", sa.String(64)),
        sa.Column("after_hash", sa.String(64)),
        sa.Column("ip_or_runtime_ref", sa.String(255), nullable=False),
        sa.Column("occurred_at", TZ, nullable=False),
        *_audit_columns(),
    )

    _evidence_link(
        "instrument_state_transition_evidence", "instrument_state_transition", "transition_id"
    )
    _evidence_link("thesis_version_evidence", "thesis_version", "thesis_version_id")
    _evidence_link("agent_opinion_evidence", "agent_opinion", "agent_opinion_id")
    _evidence_link("risk_assessment_evidence", "risk_assessment", "risk_assessment_id")
    _evidence_link("investment_decision_evidence", "investment_decision", "investment_decision_id")

    for table_name, columns in {
        "investment_policy_version": ["policy_id"],
        "portfolio_snapshot": ["portfolio_id", "as_of"],
        "position": ["portfolio_id", "instrument_id"],
        "thesis_version": ["thesis_id", "version"],
        "instrument_state_transition": ["instrument_id", "occurred_at"],
        "agent_opinion": ["agent_run_id", "instrument_id"],
        "committee_message": ["session_id", "round_number"],
        "risk_snapshot": ["portfolio_id", "as_of"],
        "investment_decision": ["portfolio_id", "instrument_id", "state"],
        "task_run": ["task_name", "scheduled_for"],
        "event_log": ["aggregate_type", "aggregate_id", "occurred_at"],
        "outbox_event": ["published_at", "created_at"],
        "audit_log": ["entity_type", "entity_id", "occurred_at"],
    }.items():
        op.create_index(f"ix_{table_name}_lookup", table_name, columns)

    op.execute(
        """
        CREATE FUNCTION reject_append_only_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'append-only table % cannot be updated or deleted', TG_TABLE_NAME
                USING ERRCODE = '55000';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table_name in (
        "investment_policy_version",
        "strategy_version",
        "portfolio_snapshot",
        "thesis_version",
        "evidence",
        "research_artifact",
        "feature_snapshot",
        "instrument_state_transition",
        "agent_opinion",
        "event_log",
        "audit_log",
        "decision_approval",
        "decision_execution",
        "decision_outcome",
        "decision_review",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation()"
        )


def downgrade() -> None:
    for table_name in (
        "investment_policy_version",
        "strategy_version",
        "portfolio_snapshot",
        "thesis_version",
        "evidence",
        "research_artifact",
        "feature_snapshot",
        "instrument_state_transition",
        "agent_opinion",
        "event_log",
        "audit_log",
        "decision_approval",
        "decision_execution",
        "decision_outcome",
        "decision_review",
    ):
        op.execute(f"DROP TRIGGER trg_{table_name}_append_only ON {table_name}")
    op.execute("DROP FUNCTION reject_append_only_mutation()")

    for table_name in (
        "investment_decision_evidence",
        "risk_assessment_evidence",
        "agent_opinion_evidence",
        "thesis_version_evidence",
        "instrument_state_transition_evidence",
    ):
        op.drop_table(table_name)

    op.drop_constraint("fk_sizing_decision", "position_sizing_run", type_="foreignkey")
    op.drop_constraint("fk_instrument_state_decision", "instrument_state", type_="foreignkey")
    op.drop_constraint("fk_thesis_current_version", "investment_thesis", type_="foreignkey")
    op.drop_constraint("fk_policy_current_version", "investment_policy", type_="foreignkey")

    for table_name in (
        "audit_log",
        "outbox_event",
        "event_log",
        "task_run",
        "decision_review",
        "decision_outcome",
        "trade_record",
        "decision_execution",
        "decision_approval",
        "investment_decision",
        "position_sizing_run",
        "risk_assessment",
        "risk_snapshot",
        "conflict_record",
        "committee_message",
        "committee_session",
        "agent_performance",
        "agent_opinion",
        "agent_run",
        "instrument_state_transition",
        "instrument_state",
        "feature_snapshot",
        "research_artifact",
        "evidence",
        "thesis_version",
        "investment_thesis",
        "position_lot",
        "position",
        "portfolio_snapshot",
        "portfolio",
        "strategy_proposal",
        "strategy_version",
        "investment_policy_version",
        "investment_policy",
        "instrument",
    ):
        op.drop_table(table_name)
