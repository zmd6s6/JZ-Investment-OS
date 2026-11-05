"""Read only explicit local scope/sources; no provider registry or credentials here."""

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from investment_os.application.daily_runtime import (
    DailyError,
    DailyEvidence,
    DailyLocalInputs,
    DailyPortfolioSnapshot,
    DailyPrepared,
)
from investment_os.application.market_data import MarketDataRequest, MarketDataSnapshot
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.infrastructure.daily_runtime_setup import capture_scope
from investment_os.infrastructure.persistence.models import (
    EvidenceRecord,
    PortfolioRecord,
    PositionRecord,
)


class DailyQuotePort(Protocol):
    async def get_snapshot(self, request: MarketDataRequest) -> MarketDataSnapshot: ...


class SqlDailyLocalReader:
    def __init__(self, quotes: DailyQuotePort):
        self.quotes = quotes

    async def read(
        self, session: AsyncSession, prepared: DailyPrepared, as_of: datetime
    ) -> DailyLocalInputs:
        command = prepared.command
        members = await capture_scope(session, command, lock=True)
        if members != prepared.members:
            raise DailyError("DAILY_SCOPE_CHANGED")
        portfolio = await session.get(PortfolioRecord, command.portfolio_id)
        if portfolio is None:
            raise DailyError("DAILY_PORTFOLIO_UNAVAILABLE")
        positions = (
            await session.scalars(
                select(PositionRecord)
                .where(PositionRecord.portfolio_id == command.portfolio_id)
                .order_by(PositionRecord.instrument_id)
            )
        ).all()
        read_at = datetime.now(UTC)
        portfolio_payload = dict(
            portfolio_id=str(portfolio.id),
            name=portfolio.name,
            base_currency=portfolio.base_currency,
            cash_balance=format(portfolio.cash_balance, "f"),
            read_at=read_at.isoformat(),
            time_semantics="CURRENT_BOOK_READ_NOT_HISTORICAL_CLOSE_SNAPSHOT",
            positions=[
                dict(
                    instrument_id=str(row.instrument_id),
                    core_quantity=format(row.core_quantity, "f"),
                    tactical_quantity=format(row.tactical_quantity, "f"),
                    core_average_cost=format(row.core_average_cost, "f"),
                    tactical_average_cost=format(row.tactical_average_cost, "f"),
                    core_reason=row.core_reason,
                    tactical_reason=row.tactical_reason,
                    version=row.version,
                )
                for row in positions
            ],
        )
        sources = set(command.evidence_source_names) | {command.quote_source_name}
        rows = (
            await session.scalars(
                select(EvidenceRecord)
                .where(
                    EvidenceRecord.instrument_id.in_(command.instrument_ids),
                    EvidenceRecord.source_name.in_(sources),
                )
                .order_by(EvidenceRecord.id)
                .limit(1001)
            )
        ).all()
        if len(rows) > 1000:
            raise DailyError("DAILY_LOCAL_EVIDENCE_RESOURCE_BOUND_EXCEEDED")
        evidence = tuple(
            DailyEvidence(
                evidence_id=row.id,
                instrument_id=row.instrument_id,
                source_name=row.source_name,
                content_hash=row.content_hash,
                observed_at=row.observed_at,
                effective_at=row.effective_at,
                available_at=row.available_at,
                ingested_at=row.ingested_at,
                expires_at=row.expires_at,
                quality_score=str(row.quality_score),
            )
            for row in rows
        )
        by_id = {row.evidence_id: row for row in evidence}
        statuses: dict[UUID, str] = {}
        references: dict[UUID, UUID] = {}
        for member in members:
            quote = await self.quotes.get_snapshot(
                MarketDataRequest(
                    instrument_id=member.instrument_id,
                    source="MANUAL_MARKET",
                    source_name=command.quote_source_name,
                    as_of=as_of,
                )
            )
            statuses[member.instrument_id] = quote.status
            if quote.status == "AVAILABLE" and quote.provenance is not None:
                row = by_id.get(quote.provenance.evidence_id)
                if (
                    row is None
                    or row.instrument_id != member.instrument_id
                    or row.source_name != command.quote_source_name
                    or row.reason(as_of) is not None
                    or row.content_hash != quote.provenance.content_hash
                ):
                    statuses[member.instrument_id] = "QUOTE_EVIDENCE_UNAVAILABLE_AS_OF"
                else:
                    references[member.instrument_id] = row.evidence_id
        result = DailyLocalInputs(
            read_at=read_at,
            portfolio_read_at=read_at,
            portfolio=DailyPortfolioSnapshot.model_validate(portfolio_payload),
            members=members,
            evidence=evidence,
            quote_statuses=statuses,
            quote_evidence_ids=references,
            content_hash="0" * 64,
        )
        return result.model_copy(
            update={
                "content_hash": fingerprint(
                    result.model_dump(mode="json", exclude={"content_hash"})
                )
            }
        )
