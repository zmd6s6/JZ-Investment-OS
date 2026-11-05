"""Bounded local monthly snapshots and historical references; no outbound capabilities."""

from datetime import datetime
from decimal import Context, Decimal, localcontext
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from investment_os.application.daily_runtime import DailyLocalInputs, DailyPrepared
from investment_os.application.market_data import MarketDataRequest, MarketDataSnapshot
from investment_os.application.monthly_review import (
    MonthlyHoldingReview,
    MonthlyPrepared,
    MonthlyReadReference,
    MonthlyReport,
)
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.domain.valuation import HoldingInput, PortfolioNumbers, value_portfolio
from investment_os.infrastructure.daily_runtime_local import DailyQuotePort, SqlDailyLocalReader
from investment_os.infrastructure.persistence.analysis_models import AnalysisRunRecord
from investment_os.infrastructure.persistence.models import (
    InstrumentRecord,
    InvestmentDecisionEvidenceRecord,
    InvestmentDecisionRecord,
    InvestmentThesisRecord,
    RiskAssessmentEvidenceRecord,
    RiskAssessmentRecord,
    ThesisVersionEvidenceRecord,
    ThesisVersionRecord,
)


class SqlMonthlyReader:
    def __init__(self, quotes: DailyQuotePort):
        self.quotes, self.local = quotes, SqlDailyLocalReader(quotes)

    async def references(
        self,
        session: AsyncSession,
        instrument_id: UUID,
        portfolio_id: UUID,
        now: datetime,
        visible: set[UUID],
    ) -> tuple[MonthlyReadReference, ...]:
        refs = []
        thesis = await session.scalar(
            select(ThesisVersionRecord)
            .join(
                InvestmentThesisRecord, ThesisVersionRecord.thesis_id == InvestmentThesisRecord.id
            )
            .where(
                InvestmentThesisRecord.instrument_id == instrument_id,
                ThesisVersionRecord.created_at <= now,
            )
            .order_by(ThesisVersionRecord.created_at.desc(), ThesisVersionRecord.id)
            .limit(1)
        )
        decision = await session.scalar(
            select(InvestmentDecisionRecord)
            .where(
                InvestmentDecisionRecord.portfolio_id == portfolio_id,
                InvestmentDecisionRecord.instrument_id == instrument_id,
                InvestmentDecisionRecord.created_at <= now,
            )
            .order_by(InvestmentDecisionRecord.created_at.desc(), InvestmentDecisionRecord.id)
            .limit(1)
        )
        # Risk must belong to a matching recorded Decision, never an unscoped committee.
        risk = (
            await session.get(RiskAssessmentRecord, decision.risk_assessment_id)
            if decision and decision.risk_assessment_id
            else None
        )
        if risk and risk.created_at > now:
            risk = None
        for kind, row, relation, parent in (
            ("THESIS", thesis, ThesisVersionEvidenceRecord, "thesis_version_id"),
            ("RISK", risk, RiskAssessmentEvidenceRecord, "risk_assessment_id"),
            ("DECISION", decision, InvestmentDecisionEvidenceRecord, "decision_id"),
        ):
            if row is None:
                continue
            ids = set(
                await session.scalars(
                    select(relation.evidence_id).where(getattr(relation, parent) == row.id)
                )
            )
            unknowns = ["HISTORICAL_REFERENCE_NOT_REVALIDATED_OR_CURRENT_APPROVAL"]
            if not ids or not ids <= visible:
                unknowns.append("REFERENCE_EVIDENCE_MISSING_EXPIRED_OR_OUTSIDE_EXPLICIT_SOURCE")
            if kind == "RISK" and risk and risk.expires_at <= now:
                unknowns.append("HISTORICAL_RISK_EXPIRED")
            status = (
                thesis.thesis_state
                if kind == "THESIS" and thesis
                else "VETO_RECORDED"
                if kind == "RISK" and risk and risk.veto
                else "HISTORICAL_NO_CURRENT_RISK_CLEARANCE"
                if kind == "RISK"
                else decision.state
                if decision
                else "UNKNOWN"
            )
            refs.append(
                MonthlyReadReference(
                    kind=kind,
                    record_id=row.id,
                    instrument_id=instrument_id,
                    recorded_at=row.created_at,
                    status=status,
                    evidence_ids=tuple(sorted(ids & visible, key=str)),
                    content_hash=row.content_hash,
                    unknowns=tuple(unknowns),
                )
            )
        analysis = await session.scalar(
            select(AnalysisRunRecord)
            .where(
                AnalysisRunRecord.portfolio_id == portfolio_id,
                AnalysisRunRecord.instrument_id == instrument_id,
                AnalysisRunRecord.queued_at <= now,
            )
            .order_by(AnalysisRunRecord.queued_at.desc(), AnalysisRunRecord.id)
            .limit(1)
        )
        if analysis:
            refs.append(
                MonthlyReadReference(
                    kind="ANALYSIS",
                    record_id=analysis.id,
                    instrument_id=instrument_id,
                    recorded_at=now,
                    status=analysis.status,
                    evidence_ids=(),
                    content_hash=fingerprint(
                        dict(
                            id=str(analysis.id),
                            status=analysis.status,
                            version=analysis.version,
                            input_hash=analysis.input_hash,
                        )
                    ),
                    unknowns=("STATUS_OBSERVED_AT_KNOWLEDGE_TIME_NOT_HISTORICAL_MONTH_END",),
                )
            )
        return tuple(refs)

    async def read(
        self,
        session: AsyncSession,
        prepared: MonthlyPrepared,
        now: datetime,
        prior: MonthlyReport | None,
    ) -> tuple[
        DailyLocalInputs,
        tuple[MonthlyHoldingReview, ...],
        PortfolioNumbers,
        tuple[MarketDataSnapshot, ...],
    ]:
        command = prepared.command
        # This DTO is only a read-only adapter; no Daily configuration or consent is persisted.
        read_scope = DailyPrepared(
            command=command.local_read_scope(),
            calendar_hash=prepared.calendar_hash,
            calendar_source=prepared.calendar_source,
            calendar_version=prepared.calendar_version,
            members=prepared.members,
            models={},
            model_pricing={},
            data_profiles=(),
            budget_hash=None,
            budget_snapshot=None,
            prepared_at=now,
            input_hash="0" * 64,
        )
        local = await self.local.read(session, read_scope, now)
        visible = {row.evidence_id for row in local.evidence if row.reason(now) is None}
        prior_positions = (
            {p.instrument_id: p for p in prior.local_inputs.portfolio.positions}
            if prior and prior.local_inputs
            else {}
        )
        metadata = {
            row.id: row
            for row in (
                await session.scalars(
                    select(InstrumentRecord).where(
                        InstrumentRecord.id.in_(command.portfolio_instrument_ids)
                    )
                )
            ).all()
        }
        inputs, quotes, holdings = [], [], []
        for position in local.portfolio.positions:
            instrument = metadata[position.instrument_id]
            quote = await self.quotes.get_snapshot(
                MarketDataRequest(
                    instrument_id=instrument.id,
                    source="MANUAL_MARKET",
                    source_name=command.quote_source_name,
                    as_of=now,
                )
            )
            quotes.append(quote)
            usable = (
                quote.status == "AVAILABLE"
                and quote.quote is not None
                and quote.provenance is not None
                and quote.provenance.evidence_id == local.quote_evidence_ids.get(instrument.id)
            )
            inputs.append(
                HoldingInput(
                    instrument.id,
                    instrument.currency,
                    instrument.sector,
                    Decimal(position.core_quantity),
                    Decimal(position.tactical_quantity),
                    quote.quote.price if usable and quote.quote else None,
                )
            )
            refs = await self.references(session, instrument.id, command.portfolio_id, now, visible)
            old = prior_positions.get(instrument.id)
            with localcontext(Context(prec=80)):
                core_change = (
                    format(Decimal(position.core_quantity) - Decimal(old.core_quantity), "f")
                    if old
                    else None
                )
                tactical_change = (
                    format(
                        Decimal(position.tactical_quantity) - Decimal(old.tactical_quantity), "f"
                    )
                    if old
                    else None
                )
            unknowns = [
                "REENTRY_WILLINGNESS_NOT_ASSESSED",
                "ANCHORING_AND_SUNK_COST_NOT_ASSESSED",
                "STYLE_DRIFT_AND_BUCKET_BALANCE_REQUIRE_EXPLICIT_POLICY_REVIEW",
            ]
            if not old:
                unknowns.append("NO_COMPARABLE_POSITION_BASELINE")
            for kind in ("THESIS", "RISK", "DECISION"):
                if not any(ref.kind == kind for ref in refs):
                    unknowns.append(f"{kind}_NOT_PROVIDED")
            holdings.append(
                MonthlyHoldingReview(
                    instrument_id=instrument.id,
                    symbol=instrument.symbol,
                    core_quantity=position.core_quantity,
                    tactical_quantity=position.tactical_quantity,
                    core_change=core_change,
                    tactical_change=tactical_change,
                    quote_status=local.quote_statuses[instrument.id],
                    references=refs,
                    unknowns=tuple(unknowns),
                )
            )
        numbers = value_portfolio("CNY", Decimal(local.portfolio.cash_balance), tuple(inputs))
        return local, tuple(holdings), numbers, tuple(quotes)
