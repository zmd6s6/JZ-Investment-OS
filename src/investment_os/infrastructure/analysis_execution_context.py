"""在模型调用前原子记录真实组合计算输入, 失败或取消仍保留已提交快照。"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.analysis_execution_context import (
    FEATURE_SET,
    ExecutionContextReceipt,
    ExecutionContextView,
    execution_input_hash,
)
from investment_os.application.analysis_progress import AnalysisCancelled
from investment_os.application.analysis_valuation import AnalysisValuation, build_analysis_valuation
from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.market_data import MarketQuote
from investment_os.application.portfolio_book import PortfolioView
from investment_os.application.research_preview import content_hash
from investment_os.infrastructure.persistence.models import (
    AnalysisJobRecord,
    AnalysisRunRecord,
    AuditLogRecord,
    EventLogRecord,
    FeatureSnapshotRecord,
)
from investment_os.infrastructure.research_preview import append_event

EVENT = "ANALYSIS_EXECUTION_CONTEXT_RECORDED"


def invalid() -> ApplicationError:
    return ApplicationError(
        ApplicationErrorCode.ANALYSIS_RESEARCH_INVALID, "execution context invalid"
    )


async def read_execution_context(
    session: AsyncSession, run: AnalysisRunRecord
) -> ExecutionContextView:
    event = await session.scalar(
        select(EventLogRecord).where(
            EventLogRecord.aggregate_type == "analysis_execution_context",
            EventLogRecord.aggregate_id == run.id,
            EventLogRecord.event_type == EVENT,
        )
    )
    if event is None:
        return ExecutionContextView(run_id=run.id, status="NOT_RECORDED")
    receipt = ExecutionContextReceipt.model_validate(event.payload_json)
    record = await session.get(FeatureSnapshotRecord, receipt.feature_snapshot_id)
    if record is None:
        raise invalid()
    valuation = AnalysisValuation.model_validate_json(json.dumps(record.values_json))
    request_hash = run.payload_json["input_snapshot"]["input_hash"]
    if (
        receipt.run_id != run.id
        or record.created_by != "analysis_runtime"
        or record.instrument_id != run.instrument_id
        or record.as_of != run.as_of
        or valuation.instrument_id != run.instrument_id
        or valuation.portfolio_id != run.portfolio_id
        or valuation.as_of != run.as_of
        or record.feature_set_version != FEATURE_SET
        or record.input_hash != valuation.input_hash
        or receipt.request_input_hash != request_hash
        or receipt.content_hash != content_hash(record.values_json)
        or receipt.runtime_input_hash != execution_input_hash(request_hash, valuation)
    ):
        raise invalid()
    audit = await session.scalar(
        select(AuditLogRecord.id).where(
            AuditLogRecord.operation == EVENT,
            AuditLogRecord.entity_id == run.id,
            AuditLogRecord.after_hash == content_hash(event.payload_json),
        )
    )
    if audit is None:
        raise invalid()
    return ExecutionContextView(
        run_id=run.id, status="RECORDED", receipt=receipt, valuation=valuation
    )


class SqlAnalysisExecutionContexts:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self._sessions = sessions

    async def read(self, run_id: UUID) -> ExecutionContextView:
        try:
            async with self._sessions() as session:
                run = await session.get(AnalysisRunRecord, run_id)
                if run is None:
                    raise ApplicationError(
                        ApplicationErrorCode.ANALYSIS_RESEARCH_NOT_FOUND, "run not found"
                    )
                return await read_execution_context(session, run)
        except (KeyError, ValueError, TypeError):
            raise invalid() from None

    async def save(
        self, run_id: UUID, valuation: AnalysisValuation, *, worker_token: UUID | None = None
    ) -> ExecutionContextReceipt:
        async with self._sessions() as session, session.begin():
            run = await session.scalar(
                select(AnalysisRunRecord).where(AnalysisRunRecord.id == run_id).with_for_update()
            )
            job = await session.get(AnalysisJobRecord, run_id)
            if (
                run is None
                or run.status != "RUNNING"
                or (
                    job is not None
                    and (
                        worker_token is None
                        or job.worker_token != worker_token
                        or job.cancel_requested_at
                    )
                )
            ):
                raise AnalysisCancelled()
            snapshot = run.payload_json["input_snapshot"]
            book = snapshot["portfolio"]
            positions = {p["instrument_id"]: p for p in book["positions"]}
            if (
                valuation.instrument_id != run.instrument_id
                or valuation.portfolio_id != run.portfolio_id
                or valuation.as_of != run.as_of
                or valuation.base_currency != book["base_currency"]
                or valuation.cash_balance != Decimal(book["cash_balance"])
                or set(positions) != {str(p.instrument_id) for p in valuation.position_values}
                or any(
                    p.core_quantity != Decimal(positions[str(p.instrument_id)]["core_quantity"])
                    or p.tactical_quantity
                    != Decimal(positions[str(p.instrument_id)]["tactical_quantity"])
                    for p in valuation.position_values
                )
            ):
                raise invalid()
            frozen_book = TypeAdapter(PortfolioView).validate_json(json.dumps(book))
            quotes = {
                p.instrument_id: MarketQuote(
                    p.instrument_id,
                    p.price,
                    p.currency,
                    p.quote_as_of,
                    p.source,
                    p.source_rank,
                    p.degraded,
                )
                for p in valuation.position_values
                if p.price is not None
                and p.quote_as_of is not None
                and p.source is not None
                and p.source_rank is not None
                and p.degraded is not None
            }
            if valuation.target_reference_price is not None:
                if valuation.target_quote_as_of is None or valuation.source is None:
                    raise invalid()
                quotes[run.instrument_id] = MarketQuote(
                    run.instrument_id,
                    valuation.target_reference_price,
                    valuation.target_currency,
                    valuation.target_quote_as_of,
                    valuation.source,
                    valuation.source_rank or 0,
                    bool(valuation.degraded),
                    daily_bar=valuation.target_market_features.bar
                    if valuation.target_market_features is not None
                    else None,
                )
            expected = build_analysis_valuation(
                portfolio=frozen_book,
                target_id=run.instrument_id,
                target_currency=valuation.target_currency,
                as_of=run.as_of,
                quotes=quotes,
            )
            if expected != valuation or (
                job is not None
                and valuation.target_currency
                != (job.request_json["request"].get("instrument_currency") or book["base_currency"])
            ):
                raise invalid()
            previous = await read_execution_context(session, run)
            if previous.receipt is not None:
                if previous.valuation != valuation:
                    raise invalid()
                return previous.receipt
            values = valuation.model_dump(mode="json")
            now = datetime.now(UTC)
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": FEATURE_SET + valuation.input_hash},
            )
            existing = await session.scalar(
                select(FeatureSnapshotRecord).where(
                    FeatureSnapshotRecord.instrument_id == run.instrument_id,
                    FeatureSnapshotRecord.as_of == run.as_of,
                    FeatureSnapshotRecord.feature_set_version == FEATURE_SET,
                    FeatureSnapshotRecord.input_hash == valuation.input_hash,
                )
            )
            if existing is not None and existing.values_json != values:
                raise invalid()
            identity = existing.id if existing is not None else uuid4()
            receipt = ExecutionContextReceipt(
                run_id=run.id,
                feature_snapshot_id=identity,
                request_input_hash=snapshot["input_hash"],
                runtime_input_hash=execution_input_hash(snapshot["input_hash"], valuation),
                content_hash=content_hash(values),
                recorded_at=now,
            )
            if existing is None:
                session.add(
                    FeatureSnapshotRecord(
                        id=identity,
                        instrument_id=run.instrument_id,
                        as_of=run.as_of,
                        feature_set_version=FEATURE_SET,
                        values_json=values,
                        input_hash=valuation.input_hash,
                        created_by="analysis_runtime",
                        correlation_id=run.id,
                        metadata_json={
                            "computed_at": now.isoformat(),
                            "scope": "PORTFOLIO_VALUATION",
                        },
                    )
                )
            await session.flush()
            payload = receipt.model_dump(mode="json")
            append_event(
                session,
                EVENT,
                run.id,
                content_hash(payload),
                payload,
                now,
                aggregate="analysis_execution_context",
                topic="analysis.inputs",
                actor_type="SYSTEM",
                actor_id="analysis_runtime",
            )
            await session.flush()
            return receipt
