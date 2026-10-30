"""Immutable numeric source reads and canonical risk/sizing persistence for AnalysisRun."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, localcontext
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.analysis_risk_engine import (
    RiskPrepared,
    compute_sizing,
    prepare_risk,
)
from investment_os.application.analysis_risk_sizing import (
    NumericFact,
    NumericSourceSnapshot,
    RiskSizingView,
    frozen_ledger_fingerprint,
    utc_now,
)
from investment_os.application.analysis_runs import AnalysisFrozenInput
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.domain.approval import DecisionApproval, DecisionApprovalHistory
from investment_os.domain.enums import Action, ApprovalAction, RiskIntent
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.analysis_risk_sizing_models import (
    AnalysisNumericEvidenceRecord,
    AnalysisNumericSourceRecord,
    AnalysisRiskResultRecord,
    AnalysisSizingResultRecord,
)
from investment_os.infrastructure.analysis_runs import append_step, audit, locked
from investment_os.infrastructure.decision_center_models import DecisionCenterActionRecord
from investment_os.infrastructure.persistence.models import (
    DecisionApprovalRecord,
    DecisionExecutionRecord,
    EvidenceRecord,
    InstrumentRecord,
    InvestmentDecisionRecord,
    InvestmentPolicyRecord,
    InvestmentPolicyVersionRecord,
    PositionSizingRunRecord,
    RiskAssessmentEvidenceRecord,
    RiskAssessmentRecord,
)


class SqlNumericSources:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self._sessions = sessions

    async def _read(
        self, session: AsyncSession, record: AnalysisNumericSourceRecord
    ) -> NumericSourceSnapshot:
        try:
            value = NumericSourceSnapshot.model_validate(record.payload_json)
            canonical = fingerprint(value.model_dump(mode="json", exclude={"content_hash"}))
            if canonical != record.content_hash or value.content_hash != canonical:
                raise ValueError("NUMERIC_SOURCE_HASH_MISMATCH")
            if (
                value.snapshot_id != record.id
                or value.portfolio_id != record.portfolio_id
                or value.instrument_id != record.instrument_id
                or value.policy_version_id != record.policy_version_id
                or value.portfolio_identity_hash != record.portfolio_identity_hash
                or value.source_kind != record.source_kind
                or value.source_name != record.source_name
                or value.as_of != record.as_of
                or value.expires_at != record.expires_at
                or value.created_at != record.created_at
                or value.target.instrument_id != record.instrument_id
            ):
                raise ValueError("NUMERIC_SOURCE_HEADER_MISMATCH")
            references = (
                await session.execute(
                    select(
                        AnalysisNumericEvidenceRecord.metric,
                        AnalysisNumericEvidenceRecord.instrument_id,
                        AnalysisNumericEvidenceRecord.evidence_id,
                    ).where(AnalysisNumericEvidenceRecord.snapshot_id == record.id)
                )
            ).all()
            if set(references) != {
                (fact.metric, fact.instrument_id, fact.evidence_id) for fact in value.facts
            }:
                raise ValueError("NUMERIC_SOURCE_REFERENCE_MISMATCH")
            evidence_ids = {fact.evidence_id for fact in value.facts}
            evidence_rows = (
                await session.scalars(
                    select(EvidenceRecord).where(EvidenceRecord.id.in_(evidence_ids))
                )
            ).all()
            if {row.id for row in evidence_rows} != evidence_ids:
                raise ValueError("NUMERIC_SOURCE_EVIDENCE_MISSING")
            extracted: dict[tuple[UUID, str, UUID], NumericFact] = {}
            for row in evidence_rows:
                payload = row.payload_json
                if payload.get("schema_version") != "numeric-facts-1.0" or not isinstance(
                    payload.get("facts"), list
                ):
                    raise ValueError("NUMERIC_SOURCE_EVIDENCE_SCHEMA_INVALID")
                for raw_fact in payload["facts"]:
                    fact = NumericFact.model_validate({**raw_fact, "evidence_id": row.id})
                    key = (row.id, fact.metric, fact.instrument_id)
                    if key in extracted:
                        raise ValueError("NUMERIC_SOURCE_EVIDENCE_DUPLICATE")
                    extracted[key] = fact
            if any(
                extracted.get((fact.evidence_id, fact.metric, fact.instrument_id)) != fact
                for fact in value.facts
            ):
                raise ValueError("NUMERIC_SOURCE_VALUE_NOT_IN_EVIDENCE")
            target = await session.get(InstrumentRecord, record.instrument_id)
            if target is None or (target.currency, target.sector, target.lot_size) != (
                value.target.currency,
                value.target.sector,
                value.target.lot_size,
            ):
                raise ValueError("NUMERIC_TARGET_METADATA_CHANGED")
            return value
        except (ValueError, TypeError, KeyError):
            raise ValueError("NUMERIC_SOURCE_INVALID") from None

    async def get(self, snapshot_id: UUID) -> NumericSourceSnapshot:
        async with self._sessions() as session:
            record = await session.get(AnalysisNumericSourceRecord, snapshot_id)
            if record is None:
                raise ValueError("NUMERIC_SOURCE_NOT_FOUND")
            return await self._read(session, record)

    async def list(
        self, portfolio_id: UUID, instrument_id: UUID
    ) -> tuple[NumericSourceSnapshot, ...]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(AnalysisNumericSourceRecord)
                    .where(
                        AnalysisNumericSourceRecord.portfolio_id == portfolio_id,
                        AnalysisNumericSourceRecord.instrument_id == instrument_id,
                    )
                    .order_by(
                        AnalysisNumericSourceRecord.created_at.desc(),
                        AnalysisNumericSourceRecord.id,
                    )
                    .limit(30)
                )
            ).all()
            return tuple([await self._read(session, row) for row in rows])


async def pending_capacity(
    session: AsyncSession, frozen: AnalysisFrozenInput
) -> tuple[tuple[Decimal, Decimal, Decimal] | None, tuple[str, ...]]:
    book = frozen.queued.valuation.input_snapshot
    at = book.captured_at
    source = frozen.numeric_source
    if source is None:
        return None, ("PENDING_NUMERIC_SOURCE_UNAVAILABLE",)
    prices = {
        fact.instrument_id: fact.value for fact in source.facts if fact.metric == "REFERENCE_PRICE"
    }
    # Ratios use the same qualified price set and frozen P5 ledger as the main evaluator.
    from investment_os.domain.valuation import HoldingInput, value_portfolio

    valuation = value_portfolio(
        book.base_currency,
        book.cash,
        tuple(
            HoldingInput(
                h.instrument_id,
                h.currency,
                h.sector,
                h.core_quantity,
                h.tactical_quantity,
                prices.get(h.instrument_id),
            )
            for h in book.holdings
        ),
    )
    if valuation.nav is None or valuation.nav <= 0:
        return None, ("PENDING_NAV_UNAVAILABLE",)
    decisions = (
        await session.scalars(
            select(InvestmentDecisionRecord).where(
                InvestmentDecisionRecord.portfolio_id == book.portfolio_id,
                InvestmentDecisionRecord.created_at <= at,
            )
        )
    ).all()
    totals = [Decimal(0), Decimal(0), Decimal(0)]
    for decision in decisions:
        approvals = (
            await session.scalars(
                select(DecisionApprovalRecord).where(
                    DecisionApprovalRecord.decision_id == decision.id,
                    DecisionApprovalRecord.created_at <= at,
                )
            )
        ).all()
        if not approvals:
            continue
        receipts = (
            await session.scalars(
                select(DecisionCenterActionRecord).where(
                    DecisionCenterActionRecord.decision_id == decision.id,
                    DecisionCenterActionRecord.occurred_at <= at,
                )
            )
        ).all()
        revisions = {
            item.approval_id: item.revision
            for item in receipts
            if item.action != "RECORD_EXECUTION"
        }
        if len(revisions) != len(approvals):
            return None, ("PENDING_LEGACY_APPROVAL_REQUIRES_REVIEW",)
        approvals = sorted(approvals, key=lambda row: revisions[row.id])
        history = DecisionApprovalHistory(
            decision.id,
            tuple(
                DecisionApproval(
                    id=row.id,
                    decision_id=decision.id,
                    actor_id=row.actor_id,
                    action=ApprovalAction(row.action),
                    occurred_at=UtcTimestamp(row.created_at),
                    expires_at=UtcTimestamp(row.expires_at) if row.expires_at else None,
                    comment=row.comment,
                )
                for row in approvals
            ),
        )
        active = history.active_approval_at(UtcTimestamp(at))
        if active is None or decision.action not in {"BUY", "ADD"}:
            continue
        sizing = await session.get(PositionSizingRunRecord, decision.position_sizing_run_id)
        if sizing is None:
            return None, ("PENDING_SIZING_MISSING",)
        try:
            requested = Decimal(str(sizing.output_json["delta_quantity"]))
            price = Decimal(str(sizing.input_json["reference_price"]))
            if not requested.is_finite() or requested <= 0 or not price.is_finite() or price <= 0:
                raise ValueError("invalid fixed pending sizing")
        except (ValueError, KeyError, ArithmeticError):
            return None, ("PENDING_SIZING_INVALID",)
        fills = (
            await session.scalars(
                select(DecisionExecutionRecord).where(
                    DecisionExecutionRecord.decision_id == decision.id,
                    DecisionExecutionRecord.created_at <= at,
                )
            )
        ).all()
        remaining = max(
            Decimal(0), requested - sum((fill.filled_quantity for fill in fills), Decimal(0))
        )
        instrument = await session.get(InstrumentRecord, decision.instrument_id)
        if instrument is None or instrument.currency != book.base_currency:
            return None, ("PENDING_FX_OR_INSTRUMENT_UNAVAILABLE",)
        with localcontext() as context:
            context.prec = 80
            weight = remaining * price / valuation.nav
            totals[2] += weight
            if decision.instrument_id == frozen.instrument_id:
                totals[0] += weight
            if instrument.sector == source.target.sector:
                totals[1] += weight
    if any(value > 1 for value in totals):
        return None, ("PENDING_EXPOSURE_OUT_OF_RANGE",)
    return (totals[0], totals[1], totals[2]), ()


class SqlAnalysisRiskSizing:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], *, now: Callable[[], datetime] = utc_now
    ):
        self._sessions = sessions
        self._now = now

    async def risk(
        self,
        run_id: UUID,
        lease: UUID,
        frozen: AnalysisFrozenInput,
        committee_id: UUID,
    ) -> RiskPrepared:
        async with self._sessions() as session, session.begin():
            record = await locked(session, run_id, lease)
            pending, pending_reasons = await pending_capacity(session, frozen)
            policy = await session.get(
                InvestmentPolicyVersionRecord,
                frozen.queued.valuation.input_snapshot.policy.version_id,
            )
            parent = (
                await session.get(InvestmentPolicyRecord, policy.policy_id, with_for_update=True)
                if policy
                else None
            )
            if policy is not None and (
                parent is None
                or parent.current_version_id != policy.id
                or parent.status != "ACTIVE"
            ):
                pending_reasons += ("POLICY_VERSION_CHANGED",)
            existing = await session.get(AnalysisRiskResultRecord, run_id)
            prepared = prepare_risk(
                frozen, pending=pending, pending_reasons=pending_reasons, evaluated_at=self._now()
            )
            if existing is not None:
                view = RiskSizingView.model_validate(existing.payload_json)
                return replace(
                    prepared,
                    view=view,
                    risk=replace(prepared.risk, id=view.risk_assessment_id)
                    if prepared.risk and view.risk_assessment_id
                    else None,
                )
            if prepared.risk is not None:
                risk = prepared.risk
                flags = prepared.view.risk_flags
                session.add(
                    RiskAssessmentRecord(
                        id=risk.id,
                        session_id=committee_id,
                        veto=risk.gate.value == "VETO",
                        veto_codes=[flag.code for flag in risk.flags if flag.kind.value == "HARD"],
                        hard_flags_json=[dict(flag) for flag in flags if flag["kind"] == "HARD"],
                        soft_flags_json=[dict(flag) for flag in flags if flag["kind"] == "SOFT"],
                        expires_at=risk.expires_at.value,
                        content_hash=risk.content_hash,
                        **audit(run_id),
                    )
                )
                await session.flush()
                session.add_all(
                    [
                        RiskAssessmentEvidenceRecord(
                            risk_assessment_id=risk.id, evidence_id=identifier
                        )
                        for identifier in set(risk.evidence_ids)
                    ]
                )
            view = prepared.view
            session.add(
                AnalysisRiskResultRecord(
                    run_id=run_id,
                    numeric_snapshot_id=view.numeric_snapshot_id,
                    risk_assessment_id=view.risk_assessment_id,
                    input_hash=frozen.input_hash,
                    status=view.risk_gate,
                    payload_json=view.model_dump(mode="json"),
                    **audit(run_id),
                )
            )
            await append_step(
                session,
                record,
                stage="RISK",
                status="COMPLETED" if prepared.risk else "BLOCKED",
                payload=view.model_dump(mode="json"),
                reason_code=None if prepared.risk else "DETERMINISTIC_RISK_INPUTS_UNAVAILABLE",
            )
            return prepared

    async def sizing(
        self,
        run_id: UUID,
        lease: UUID,
        frozen: AnalysisFrozenInput,
        prepared: RiskPrepared,
        *,
        action: Action,
        intent: RiskIntent,
    ) -> RiskSizingView:
        async with self._sessions() as session, session.begin():
            record = await locked(session, run_id, lease)
            existing = await session.get(AnalysisSizingResultRecord, run_id)
            if existing is not None:
                return RiskSizingView.model_validate(existing.payload_json)
            version = (
                await session.get(InvestmentPolicyVersionRecord, prepared.view.policy_version_id)
                if prepared.view.policy_version_id
                else None
            )
            parent = (
                await session.get(InvestmentPolicyRecord, version.policy_id, with_for_update=True)
                if version
                else None
            )
            now = self._now()
            view, request = compute_sizing(prepared, frozen, action=action, intent=intent)
            if version is not None and (
                parent is None
                or parent.current_version_id != version.id
                or parent.status != "ACTIVE"
            ):
                view = view.model_copy(
                    update={
                        "sizing_status": "BLOCKED",
                        "blockers": ("POLICY_VERSION_CHANGED",),
                        "target_quantity": None,
                        "delta_quantity": None,
                        "sizing_input": None,
                        "sizing_output": None,
                    }
                )
                request = None
            if view.expires_at is not None and now >= view.expires_at:
                view = view.model_copy(
                    update={
                        "sizing_status": "BLOCKED",
                        "blockers": ("RISK_EXPIRED_BEFORE_SIZING",),
                        "target_quantity": None,
                        "delta_quantity": None,
                        "sizing_input": None,
                        "sizing_output": None,
                    }
                )
                request = None
            if request is not None:
                identifier = uuid4()
                assert view.sizing_output is not None and view.sizing_input is not None
                assert prepared.policy is not None and prepared.policy.sizing is not None
                inputs = {
                    "request": view.sizing_input,
                    "formula": prepared.policy.sizing.to_formula(),
                    "reference_price": str(request.reference_price),
                    "analysis_input_hash": frozen.input_hash,
                    "ledger_hash": frozen_ledger_fingerprint(
                        frozen.queued.valuation.input_snapshot
                    ),
                }
                formula = prepared.policy.sizing.to_formula()
                inputs["formula"] = {
                    "version": formula.version,
                    "intent_weights": {
                        key.value: {"value": str(value.value)}
                        for key, value in formula.intent_weights.items()
                    },
                    "target_volatility": str(formula.target_volatility),
                    "volatility_floor": str(formula.volatility_floor),
                    "volatility_scale_min": str(formula.volatility_scale_min),
                    "volatility_scale_max": str(formula.volatility_scale_max),
                    "reduce_fraction": {"value": str(formula.reduce_fraction.value)},
                }
                session.add(
                    PositionSizingRunRecord(
                        id=identifier,
                        portfolio_id=frozen.queued.command.portfolio_id,
                        instrument_id=frozen.instrument_id,
                        policy_version_id=frozen.queued.valuation.input_snapshot.policy.version_id,
                        input_json=inputs,
                        formula_version=prepared.policy.sizing.formula_version,
                        output_json=view.sizing_output,
                        input_hash=str(view.sizing_output["input_hash"]),
                        **audit(run_id),
                    )
                )
                await session.flush()
                view = view.model_copy(update={"sizing_run_id": identifier})
            session.add(
                AnalysisSizingResultRecord(
                    run_id=run_id,
                    sizing_run_id=view.sizing_run_id,
                    input_hash=frozen.input_hash,
                    status=view.sizing_status,
                    payload_json=view.model_dump(mode="json"),
                    **audit(run_id),
                )
            )
            await append_step(
                session,
                record,
                stage="SIZING",
                status="COMPLETED" if request else "BLOCKED",
                payload=view.model_dump(mode="json"),
                reason_code=None if request else "SIZING_INPUTS_INCOMPLETE",
            )
            return view
