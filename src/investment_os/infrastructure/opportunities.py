"""Append-only finite screening facts and immutable query snapshots, no network calls."""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.evidence import normalize_artifact
from investment_os.application.instrument_catalog import (
    InstrumentCatalogEntry,
    InstrumentCatalogService,
)
from investment_os.application.opportunities import (
    FactReceipt,
    FactSnapshot,
    FunnelQuery,
    FunnelRun,
    ManualScreenFacts,
    OpportunityError,
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


def digest(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def fact_artifact(command: ManualScreenFacts) -> ResearchArtifactDTO:
    return ResearchArtifactDTO(
        provider="MANUAL_SCREEN_FACTS",
        provider_ref=str(command.instrument_id),
        artifact_type="FINANCIAL",
        instrument_id=command.instrument_id,
        source_name=command.source_name,
        source_locator=command.source_locator,
        source_tier="OTHER",
        observed_at=UtcTimestamp(command.observed_at),
        effective_at=UtcTimestamp(command.effective_at),
        available_at=UtcTimestamp(command.available_at),
        expires_at=UtcTimestamp(command.expires_at),
        source_schema_version="manual-screen-facts-v1",
        payload={
            "facts": command.model_dump(mode="json", exclude={"request_id"}),
            "manual_unverified": True,
        },
    )


class LocalExplicitUniverse:
    def __init__(self, catalog: InstrumentCatalogService):
        self._catalog = catalog

    async def resolve(self, instrument_ids: tuple[UUID, ...]) -> tuple[InstrumentCatalogEntry, ...]:
        return tuple([await self._catalog.get(identifier) for identifier in instrument_ids])


class SqlOpportunityStore:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        now: Callable[[], datetime] | None = None,
    ):
        self._sessions = sessions
        self._now = now or (lambda: datetime.now(UTC))

    async def _lock(self, uow: SqlAlchemyUnitOfWork, kind: str, identifier: UUID) -> None:
        await uow.session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": advisory_lock_key(kind, str(identifier))},
        )

    async def _receipt(
        self, uow: SqlAlchemyUnitOfWork, kind: str, identifier: UUID
    ) -> EventLogRecord | None:
        record: EventLogRecord | None = await uow.session.scalar(
            select(EventLogRecord).where(
                EventLogRecord.aggregate_type == kind, EventLogRecord.aggregate_id == identifier
            )
        )
        return record

    async def _audit_event(
        self,
        uow: SqlAlchemyUnitOfWork,
        *,
        kind: str,
        identifier: UUID,
        operation: str,
        payload: dict[str, object],
        content_hash: str,
        now: datetime,
    ) -> None:
        event = EventLogRecord(
            id=uuid4(),
            event_type=operation,
            aggregate_type=kind,
            aggregate_id=identifier,
            occurred_at=now,
            correlation_id=identifier,
            created_by="opportunity_funnel",
            payload_json=payload,
        )
        await uow.events.append(event)
        await uow.audit.append(
            AuditLogRecord(
                actor_type="HUMAN",
                actor_id="local-owner",
                operation=operation,
                entity_type=kind,
                entity_id=identifier,
                before_hash=None,
                after_hash=content_hash,
                ip_or_runtime_ref="opportunity_funnel",
                occurred_at=now,
                correlation_id=identifier,
                created_by="opportunity_funnel",
            )
        )
        await uow.outbox.add(
            OutboxEventRecord(
                event_id=event.id,
                topic="opportunity.snapshot.recorded",
                payload_json={"id": str(identifier), "content_hash": content_hash},
                created_by="opportunity_funnel",
                correlation_id=identifier,
            )
        )

    async def save_facts(self, command: ManualScreenFacts) -> FactReceipt:
        fingerprint = digest(command.model_dump(mode="json", exclude={"request_id"}))
        now = self._now()
        normalized = normalize_artifact(fact_artifact(command), ingested_at=now)
        async with SqlAlchemyUnitOfWork(self._sessions) as uow:
            await self._lock(uow, "manual-screen-facts", command.request_id)
            previous = await self._receipt(uow, "manual_screen_facts", command.request_id)
            if previous:
                if previous.payload_json["request_hash"] != fingerprint:
                    raise OpportunityError("REQUEST_CONTENT_CONFLICT")
                return FactReceipt.model_validate(previous.payload_json["receipt"])
            instrument = await uow.session.scalar(
                select(InstrumentRecord)
                .where(InstrumentRecord.id == command.instrument_id)
                .with_for_update()
            )
            if instrument is None:
                raise OpportunityError("INSTRUMENT_NOT_FOUND")
            if instrument.currency != "CNY":
                raise OpportunityError("FX_REQUIRED")
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
                    evidence_type="FINANCIAL",
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
                    created_by="opportunity_funnel",
                    correlation_id=command.request_id,
                    metadata_json={
                        "provider": "MANUAL_SCREEN_FACTS",
                        "source_schema_version": "manual-screen-facts-v1",
                    },
                )
                await uow.evidence.append(record)
                await uow.research_artifacts.append(
                    ResearchArtifactRecord(
                        provider="MANUAL_SCREEN_FACTS",
                        provider_ref=str(command.instrument_id),
                        artifact_type="FINANCIAL",
                        as_of=command.available_at,
                        raw_payload_ref=command.source_locator,
                        normalized_payload_json=dict(normalized.payload),
                        content_hash=normalized.content_hash,
                        created_by="opportunity_funnel",
                        correlation_id=command.request_id,
                        metadata_json={"source_schema_version": "manual-screen-facts-v1"},
                    )
                )
            receipt = FactReceipt(
                request_id=command.request_id,
                evidence_id=record.id,
                content_hash=record.content_hash,
                ingested_at=record.ingested_at,
            )
            await self._audit_event(
                uow,
                kind="manual_screen_facts",
                identifier=command.request_id,
                operation="MANUAL_SCREEN_FACTS_RECORDED",
                payload={"request_hash": fingerprint, "receipt": receipt.model_dump(mode="json")},
                content_hash=record.content_hash,
                now=now,
            )
            await uow.commit()
            return receipt

    async def get_facts(
        self, instrument_id: UUID, source_name: str, as_of: datetime
    ) -> FactSnapshot:
        async with self._sessions() as session:
            record = await session.scalar(
                select(EvidenceRecord)
                .where(
                    EvidenceRecord.instrument_id == instrument_id,
                    EvidenceRecord.source_name == source_name,
                    EvidenceRecord.metadata_json["provider"].astext == "MANUAL_SCREEN_FACTS",
                    EvidenceRecord.ingested_at <= as_of,
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
                return FactSnapshot(status="MISSING")
            try:
                facts = ManualScreenFacts.model_validate(
                    {"request_id": record.correlation_id, **record.payload_json["facts"]}
                )
                normalized = normalize_artifact(
                    fact_artifact(facts), ingested_at=record.ingested_at
                )
                if (
                    record.evidence_type != "FINANCIAL"
                    or normalized.content_hash != record.content_hash
                    or dict(normalized.payload) != record.payload_json
                    or facts.instrument_id != record.instrument_id
                    or facts.source_name != record.source_name
                    or facts.source_locator != record.source_locator
                    or facts.observed_at != record.observed_at
                    or facts.effective_at != record.effective_at
                    or facts.available_at != record.available_at
                    or facts.expires_at != record.expires_at
                    or record.metadata_json.get("source_schema_version") != "manual-screen-facts-v1"
                ):
                    raise ValueError("fact verification failed")
            except (ValueError, TypeError, KeyError):
                return FactSnapshot(status="INVALID")
            status = "AVAILABLE"
            if facts.available_at > as_of:
                status = "NOT_YET_AVAILABLE"
            elif facts.expires_at <= as_of:
                status = "EXPIRED"
            return FactSnapshot(
                status=status,
                facts=facts,
                evidence_id=record.id,
                content_hash=record.content_hash,
                ingested_at=record.ingested_at,
            )

    async def replay(self, query: FunnelQuery) -> FunnelRun | None:
        async with SqlAlchemyUnitOfWork(self._sessions) as uow:
            previous = await self._receipt(uow, "opportunity_funnel_run", query.request_id)
            if previous is None:
                return None
            if previous.payload_json["request_hash"] != digest(query.model_dump(mode="json")):
                raise OpportunityError("REQUEST_CONTENT_CONFLICT")
            return self._read_run(previous)

    @staticmethod
    def _read_run(record: EventLogRecord) -> FunnelRun:
        try:
            raw = record.payload_json["run"]
            if digest(raw) != record.payload_json["snapshot_hash"]:
                raise OpportunityError("RUN_SNAPSHOT_INVALID")
            run = FunnelRun.model_validate(raw)
            if (
                run.run_id != record.aggregate_id
                or digest(run.query.model_dump(mode="json")) != record.payload_json["request_hash"]
            ):
                raise OpportunityError("RUN_SNAPSHOT_INVALID")
            return run
        except (ValueError, TypeError, KeyError):
            raise OpportunityError("RUN_SNAPSHOT_INVALID") from None

    async def save_run(self, run: FunnelRun) -> FunnelRun:
        async with SqlAlchemyUnitOfWork(self._sessions) as uow:
            result = await self.save_run_in(uow, run)
            await uow.commit()
            return result

    async def save_run_in(self, uow: SqlAlchemyUnitOfWork, run: FunnelRun) -> FunnelRun:
        """Persist using the caller transaction; never commit a scheduled partial effect."""
        fingerprint = digest(run.query.model_dump(mode="json"))
        await self._lock(uow, "opportunity-funnel-run", run.run_id)
        previous = await self._receipt(uow, "opportunity_funnel_run", run.run_id)
        if previous:
            if previous.payload_json["request_hash"] != fingerprint:
                raise OpportunityError("REQUEST_CONTENT_CONFLICT")
            return self._read_run(previous)
        raw = run.model_dump(mode="json")
        snapshot_hash = digest(raw)
        await self._audit_event(
            uow,
            kind="opportunity_funnel_run",
            identifier=run.run_id,
            operation="OPPORTUNITY_FUNNEL_RECORDED",
            payload={"request_hash": fingerprint, "snapshot_hash": snapshot_hash, "run": raw},
            content_hash=snapshot_hash,
            now=self._now(),
        )
        return run

    async def get_run(self, run_id: UUID) -> FunnelRun | None:
        async with SqlAlchemyUnitOfWork(self._sessions) as uow:
            record = await self._receipt(uow, "opportunity_funnel_run", run_id)
            return self._read_run(record) if record else None

    async def list_runs(self) -> tuple[FunnelRun, ...]:
        async with self._sessions() as session:
            records = (
                await session.scalars(
                    select(EventLogRecord)
                    .where(EventLogRecord.aggregate_type == "opportunity_funnel_run")
                    .order_by(EventLogRecord.occurred_at.desc(), EventLogRecord.id.desc())
                    .limit(20)
                )
            ).all()
            return tuple(self._read_run(record) for record in records)
