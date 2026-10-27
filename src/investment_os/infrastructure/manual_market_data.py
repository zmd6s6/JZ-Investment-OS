"""Immutable manual reference prices with atomic receipts and explicit source reads."""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.evidence import normalize_artifact
from investment_os.application.market_data import (
    ManualQuoteInput,
    ManualQuoteSaved,
    MarketDataError,
    MarketDataRequest,
    MarketDataSnapshot,
    MarketQuote,
    QuoteProvenance,
    unavailable,
)
from investment_os.application.research import ResearchArtifactDTO
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.persistence.locks import advisory_lock_key
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    EventLogRecord,
    EvidenceRecord,
    InstrumentRecord,
    OutboxEventRecord,
    ResearchArtifactRecord,
)
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork


def quote_artifact(command: ManualQuoteInput) -> ResearchArtifactDTO:
    return ResearchArtifactDTO(
        provider="MANUAL_MARKET",
        provider_ref=str(command.instrument_id),
        artifact_type="MARKET",
        instrument_id=command.instrument_id,
        source_name=command.source_name,
        source_locator=command.source_locator,
        source_tier="OTHER",
        observed_at=UtcTimestamp(command.observed_at),
        effective_at=UtcTimestamp(command.effective_at),
        available_at=UtcTimestamp(command.available_at),
        expires_at=UtcTimestamp(command.expires_at),
        payload={
            "quote": command.model_dump(mode="json", exclude={"request_id"}),
            "manual_unverified": True,
        },
        source_schema_version="manual-market-v1",
    )


class SqlManualMarketData:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        now: Callable[[], datetime] | None = None,
    ):
        self._sessions = sessions
        self._now = now or (lambda: datetime.now(UTC))

    async def save_quote(self, command: ManualQuoteInput) -> ManualQuoteSaved:
        encoded = json.dumps(
            command.model_dump(mode="json", exclude={"request_id"}),
            sort_keys=True,
            separators=(",", ":"),
        )
        fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        now = self._now()
        normalized = normalize_artifact(quote_artifact(command), ingested_at=now)
        async with SqlAlchemyUnitOfWork(self._sessions) as uow:
            await uow.session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": advisory_lock_key("manual-market-request", str(command.request_id))},
            )
            replay = await uow.session.scalar(
                select(EventLogRecord).where(
                    EventLogRecord.aggregate_type == "manual_market_write",
                    EventLogRecord.aggregate_id == command.request_id,
                )
            )
            if replay:
                if replay.payload_json["request_hash"] != fingerprint:
                    raise MarketDataError("MARKET_REQUEST_CONFLICT")
                return ManualQuoteSaved.model_validate(replay.payload_json["result"])
            # Identity metadata cannot change between validation and the committed quote.
            instrument = await uow.session.scalar(
                select(InstrumentRecord)
                .where(InstrumentRecord.id == command.instrument_id)
                .with_for_update()
            )
            if instrument is None:
                raise MarketDataError("MARKET_INSTRUMENT_NOT_FOUND")
            if instrument.currency != "CNY" or command.currency != "CNY":
                raise MarketDataError("FX_REQUIRED")
            existing = await uow.evidence.get_by_source_content(
                source_name=command.source_name,
                source_locator=command.source_locator,
                content_hash=normalized.content_hash,
            )
            if existing:
                record = existing
            else:
                record = EvidenceRecord(
                    id=uuid4(),
                    instrument_id=command.instrument_id,
                    evidence_type="MARKET",
                    source_name=command.source_name,
                    source_locator=command.source_locator,
                    source_tier="OTHER",
                    observed_at=command.observed_at,
                    effective_at=command.effective_at,
                    available_at=command.available_at,
                    ingested_at=now,
                    expires_at=command.expires_at,
                    quality_score=normalized.quality_score,
                    freshness_status=normalized.freshness_status.value,
                    payload_json=dict(normalized.payload),
                    content_hash=normalized.content_hash,
                    created_by="manual_market",
                    correlation_id=command.request_id,
                    metadata_json={
                        "provider": "MANUAL_MARKET",
                        "provider_ref": str(command.instrument_id),
                        "source_schema_version": "manual-market-v1",
                    },
                )
                await uow.evidence.append(record)
                await uow.research_artifacts.append(
                    ResearchArtifactRecord(
                        provider="MANUAL_MARKET",
                        provider_ref=str(command.instrument_id),
                        artifact_type="MARKET",
                        as_of=command.available_at,
                        raw_payload_ref=command.source_locator,
                        normalized_payload_json=dict(normalized.payload),
                        content_hash=normalized.content_hash,
                        created_by="manual_market",
                        correlation_id=command.request_id,
                        metadata_json={"source_schema_version": "manual-market-v1"},
                    )
                )
            saved = ManualQuoteSaved(
                request_id=command.request_id,
                evidence_id=record.id,
                content_hash=record.content_hash,
                ingested_at=record.ingested_at,
            )
            event = EventLogRecord(
                id=uuid4(),
                event_type="MANUAL_MARKET_QUOTE_RECORDED",
                aggregate_type="manual_market_write",
                aggregate_id=command.request_id,
                occurred_at=now,
                correlation_id=command.request_id,
                created_by="manual_market",
                payload_json={"request_hash": fingerprint, "result": saved.model_dump(mode="json")},
            )
            await uow.events.append(event)
            await uow.audit.append(
                AuditLogRecord(
                    actor_type="HUMAN",
                    actor_id="local-owner",
                    operation="MANUAL_MARKET_QUOTE_RECORDED",
                    entity_type="evidence",
                    entity_id=record.id,
                    before_hash=None,
                    after_hash=record.content_hash,
                    ip_or_runtime_ref="manual_market",
                    occurred_at=now,
                    correlation_id=command.request_id,
                    created_by="manual_market",
                )
            )
            await uow.outbox.add(
                OutboxEventRecord(
                    event_id=event.id,
                    topic="market.quote.recorded",
                    payload_json={
                        "evidence_id": str(record.id),
                        "content_hash": record.content_hash,
                    },
                    created_by="manual_market",
                    correlation_id=command.request_id,
                )
            )
            await uow.commit()
            return saved

    async def get_snapshot(self, request: MarketDataRequest) -> MarketDataSnapshot:
        async with self._sessions() as session:
            record = await session.scalar(
                select(EvidenceRecord)
                .where(
                    EvidenceRecord.instrument_id == request.instrument_id,
                    EvidenceRecord.source_name == request.source_name,
                    EvidenceRecord.evidence_type == "MARKET",
                    EvidenceRecord.metadata_json["provider"].astext == "MANUAL_MARKET",
                    EvidenceRecord.ingested_at <= request.as_of,
                )
                .order_by(
                    EvidenceRecord.effective_at.desc(),
                    EvidenceRecord.available_at.desc(),
                    EvidenceRecord.ingested_at.desc(),
                    EvidenceRecord.id.desc(),
                )
                .limit(1)
            )
            if record is None:
                return unavailable(request, "MISSING", "NO_QUOTE_FOR_EXPLICIT_SOURCE_AS_OF")
            try:
                command = ManualQuoteInput.model_validate(
                    {"request_id": UUID(int=0), **record.payload_json["quote"]}
                )
                normalized = normalize_artifact(
                    quote_artifact(command), ingested_at=record.ingested_at
                )
                if (
                    normalized.content_hash != record.content_hash
                    or record.payload_json != dict(normalized.payload)
                    or command.instrument_id != record.instrument_id
                    or command.source_name != record.source_name
                    or command.source_locator != record.source_locator
                    or command.observed_at != record.observed_at
                    or command.effective_at != record.effective_at
                    or command.available_at != record.available_at
                    or command.expires_at != record.expires_at
                    or record.metadata_json.get("source_schema_version") != "manual-market-v1"
                ):
                    raise ValueError("stored manual quote cannot be verified")
                provenance = QuoteProvenance(
                    instrument_id=command.instrument_id,
                    evidence_id=record.id,
                    content_hash=record.content_hash,
                    source_name=command.source_name,
                    source_locator=command.source_locator,
                    currency=command.currency,
                    observed_at=command.observed_at,
                    effective_at=command.effective_at,
                    available_at=command.available_at,
                    expires_at=command.expires_at,
                    ingested_at=record.ingested_at,
                )
            except (ValueError, TypeError, KeyError):
                return unavailable(request, "INVALID", "STORED_QUOTE_INVALID")
            if command.currency != request.base_currency or command.currency != "CNY":
                result = unavailable(request, "FX_REQUIRED", "FX_INPUT_NOT_AVAILABLE")
            elif command.available_at > request.as_of:
                result = unavailable(request, "NOT_YET_AVAILABLE", "QUOTE_NOT_YET_AVAILABLE")
            elif command.expires_at <= request.as_of:
                result = unavailable(request, "EXPIRED", "QUOTE_EXPIRED")
            else:
                return MarketDataSnapshot(
                    **request.model_dump(exclude={"portfolio_id"}),
                    status="AVAILABLE",
                    reason_code="MANUAL_UNVERIFIED_REFERENCE_ONLY",
                    quote=MarketQuote(price=Decimal(command.price), provenance=provenance),
                    provenance=provenance,
                )
            return result.model_copy(update={"provenance": provenance})
