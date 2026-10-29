"""Transactional, append-only membership intake; no provider or model dependency."""

import hashlib
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.evidence import normalize_artifact
from investment_os.application.opportunities import FunnelQuery, FunnelRun, OpportunityError
from investment_os.application.research import ResearchArtifactDTO
from investment_os.application.universe_snapshots import (
    UniverseBoundRun,
    UniverseConfirm,
    UniverseError,
    UniverseImport,
    UniverseMember,
    UniverseOrigin,
    UniversePreview,
    UniverseRun,
    UniverseScopeNotYetAvailable,
    UniverseSnapshot,
    UniverseSource,
    UniverseSummary,
    fingerprint,
    parse_members,
)
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.opportunities import SqlOpportunityStore
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
from investment_os.infrastructure.universe_models import (
    UniverseMemberRecord,
    UniverseRunRecord,
    UniverseSnapshotRecord,
)

PROVIDER = "MANUAL_UNIVERSE"


def common(identifier: UUID) -> dict[str, object]:
    return {
        "created_by": "universe_intake",
        "correlation_id": identifier,
        "schema_version": "1.0",
        "metadata_json": {},
    }


def artifact(source: UniverseSource, payload: dict[str, object]) -> ResearchArtifactDTO:
    return ResearchArtifactDTO(
        provider=PROVIDER,
        provider_ref=str(payload["file_hash"]),
        artifact_type="MARKET",
        source_name=source.source_name,
        source_locator=source.source_locator,
        source_tier="OTHER",
        observed_at=UtcTimestamp(source.observed_at),
        effective_at=UtcTimestamp(source.effective_at),
        available_at=UtcTimestamp(source.available_at),
        payload=payload,
        source_schema_version="universe-source-csv-v1",
    )


def member(record: InstrumentRecord | UniverseMemberRecord) -> UniverseMember:
    if record.currency != "CNY":
        raise UniverseError("UNIVERSE_CURRENCY_UNSUPPORTED")
    return UniverseMember(
        instrument_id=record.id if isinstance(record, InstrumentRecord) else record.instrument_id,
        market=record.exchange if isinstance(record, InstrumentRecord) else record.market,
        symbol=record.symbol,
        name=record.name,
        currency="CNY",
        asset_type=record.asset_type,
    )


def summary(snapshot: UniverseSnapshot) -> UniverseSummary:
    return UniverseSummary.model_validate(snapshot.model_dump(exclude={"members"}))


async def lock(session: AsyncSession, namespace: str, identifier: UUID | str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": advisory_lock_key(namespace, str(identifier))},
    )


async def emit(
    uow: SqlAlchemyUnitOfWork,
    kind: str,
    identifier: UUID,
    payload: dict[str, object],
    now: datetime,
) -> None:
    event = EventLogRecord(
        id=uuid4(),
        event_type=kind,
        aggregate_type="universe_intake",
        aggregate_id=identifier,
        occurred_at=now,
        payload_json=payload,
        **common(identifier),
    )
    await uow.events.append(event)
    await uow.audit.append(
        AuditLogRecord(
            actor_type="HUMAN",
            actor_id="local-owner",
            operation=kind,
            entity_type="UniverseSnapshot",
            entity_id=identifier,
            before_hash=None,
            after_hash=fingerprint(payload),
            ip_or_runtime_ref="universe_intake",
            occurred_at=now,
            **common(identifier),
        )
    )
    await uow.outbox.add(
        OutboxEventRecord(
            event_id=event.id,
            topic=kind,
            payload_json={"id": str(identifier), "content_hash": fingerprint(payload)},
            **common(identifier),
        )
    )


class SqlUniverseSnapshots:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions
        self.funnels = SqlOpportunityStore(sessions)

    async def validate_scope(self, query: FunnelQuery) -> None:
        """Enforce a frozen import's identity and time in every production screening path."""
        if not query.scope_locator.startswith("universe_snapshot:"):
            return
        try:
            _, identifier, _ = query.scope_locator.split(":")
            snapshot = await self.get(UUID(identifier))
        except (ValueError, UniverseError):
            raise OpportunityError("UNIVERSE_SCOPE_INVALID") from None
        if (
            query.scope_locator
            != f"universe_snapshot:{snapshot.snapshot_id}:{snapshot.content_hash}"
            or query.scope_name != snapshot.source.source_name
            or set(query.instrument_ids) != {m.instrument_id for m in snapshot.members}
            or len(snapshot.members) > 200
        ):
            raise OpportunityError("UNIVERSE_SCOPE_INVALID")
        if query.as_of < max(
            snapshot.source.observed_at,
            snapshot.source.effective_at,
            snapshot.source.available_at,
            snapshot.ingested_at,
        ):
            raise UniverseScopeNotYetAvailable("UNIVERSE_NOT_YET_AVAILABLE")

    async def resolve(self, market: str, symbols: tuple[str, ...]) -> tuple[UniverseMember, ...]:
        async with self.sessions() as session:
            records = (
                await session.scalars(
                    select(InstrumentRecord).where(
                        InstrumentRecord.exchange == market, InstrumentRecord.symbol.in_(symbols)
                    )
                )
            ).all()
            return tuple(member(row) for row in records)

    async def _snapshot(self, session: AsyncSession, identifier: UUID) -> UniverseSnapshot:
        record = await session.get(UniverseSnapshotRecord, identifier)
        if record is None:
            raise UniverseError("UNIVERSE_NOT_FOUND")
        try:
            source = UniverseSource.model_validate(record.source_json)
            members = tuple(
                member(row)
                for row in (
                    await session.scalars(
                        select(UniverseMemberRecord)
                        .where(UniverseMemberRecord.snapshot_id == identifier)
                        .order_by(
                            UniverseMemberRecord.market,
                            UniverseMemberRecord.symbol,
                            UniverseMemberRecord.instrument_id,
                        )
                    )
                ).all()
            )
            evidence = await session.get(EvidenceRecord, record.evidence_id)
            if evidence is None:
                raise ValueError("missing membership evidence")
            raw = evidence.payload_json
            csv_text = raw["csv_text"]
            if not isinstance(csv_text, str):
                raise ValueError("invalid membership text")
            symbols = parse_members(UniverseImport(source=source, csv_text=csv_text))
            encoded_members = [m.model_dump(mode="json") for m in members]
            normalized = normalize_artifact(artifact(source, raw), ingested_at=evidence.ingested_at)
            if (
                len(members) != record.member_count
                or record.member_count != source.declared_total
                or len(set(symbols)) != len(members)
                or set(symbols) != {m.symbol for m in members}
                or any(m.market != source.market for m in members)
                or fingerprint(encoded_members) != record.members_hash
                or hashlib.sha256(csv_text.encode("utf-8")).hexdigest() != record.file_hash
                or raw.get("source") != source.model_dump(mode="json")
                or raw.get("members") != encoded_members
                or raw.get("file_hash") != record.file_hash
                or raw.get("members_hash") != record.members_hash
                or raw.get("legal_use_acknowledgement") is not True
                or raw.get("declaration_acknowledgement") is not True
                or evidence.instrument_id is not None
                or evidence.evidence_type != "MARKET"
                or evidence.source_name != source.source_name
                or evidence.source_locator != source.source_locator
                or evidence.observed_at != source.observed_at
                or evidence.effective_at != source.effective_at
                or evidence.available_at != source.available_at
                or evidence.metadata_json.get("provider") != PROVIDER
                or normalized.content_hash != evidence.content_hash
                or max(source.observed_at, source.effective_at, source.available_at)
                > record.ingested_at
            ):
                raise ValueError("membership snapshot mismatch")
            snapshot = UniverseSnapshot(
                snapshot_id=record.id,
                source=source,
                members=members,
                ingested_at=record.ingested_at,
                evidence_id=record.evidence_id,
                file_hash=record.file_hash,
                members_hash=record.members_hash,
                content_hash=record.content_hash,
                member_count=record.member_count,
            )
            if (
                fingerprint(snapshot.model_dump(mode="json", exclude={"content_hash"}))
                != record.content_hash
            ):
                raise ValueError("membership hash mismatch")
            return snapshot
        except (ValueError, KeyError, TypeError):
            raise UniverseError("UNIVERSE_SNAPSHOT_INVALID") from None

    async def get(self, snapshot_id: UUID) -> UniverseSnapshot:
        async with self.sessions() as session:
            return await self._snapshot(session, snapshot_id)

    async def list(self) -> tuple[UniverseSummary, ...]:
        async with self.sessions() as session:
            identifiers = (
                await session.scalars(
                    select(UniverseSnapshotRecord.id)
                    .order_by(UniverseSnapshotRecord.created_at.desc(), UniverseSnapshotRecord.id)
                    .limit(20)
                )
            ).all()
            return tuple(
                [summary(await self._snapshot(session, identifier)) for identifier in identifiers]
            )

    async def replay_import(self, command: UniverseConfirm) -> UniverseSnapshot | None:
        async with self.sessions() as session:
            record = await session.get(UniverseSnapshotRecord, command.request_id)
            if record is None:
                return None
            if record.request_hash != fingerprint(command.model_dump(mode="json")):
                raise UniverseError("REQUEST_CONTENT_CONFLICT")
            return await self._snapshot(session, command.request_id)

    async def save_import(
        self, command: UniverseConfirm, preview: UniversePreview, now: datetime
    ) -> UniverseSnapshot:
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            await lock(uow.session, "universe-snapshot", command.request_id)
            replay = await uow.session.get(UniverseSnapshotRecord, command.request_id)
            if replay:
                if replay.request_hash != fingerprint(command.model_dump(mode="json")):
                    raise UniverseError("REQUEST_CONTENT_CONFLICT")
                return await self._snapshot(uow.session, command.request_id)
            records = (
                await uow.session.scalars(
                    select(InstrumentRecord)
                    .where(InstrumentRecord.id.in_(m.instrument_id for m in preview.members))
                    .with_for_update(read=True)
                )
            ).all()
            frozen = {m.instrument_id: m for m in preview.members}
            if len(records) != len(frozen) or any(
                member(row) != frozen.get(row.id) for row in records
            ):
                raise UniverseError("UNIVERSE_PREVIEW_CONFLICT")
            payload = {
                "source": preview.source.model_dump(mode="json"),
                "csv_text": command.csv_text,
                "file_hash": preview.file_hash,
                "members_hash": preview.members_hash,
                "members": [m.model_dump(mode="json") for m in preview.members],
                "legal_use_acknowledgement": True,
                "declaration_acknowledgement": True,
                "manual_unverified": True,
            }
            normalized = normalize_artifact(artifact(preview.source, payload), ingested_at=now)
            await lock(
                uow.session,
                "universe-evidence",
                fingerprint(
                    {
                        "source_name": preview.source.source_name,
                        "source_locator": preview.source.source_locator,
                        "content_hash": normalized.content_hash,
                    }
                ),
            )
            evidence = await uow.evidence.get_by_source_content(
                source_name=preview.source.source_name,
                source_locator=preview.source.source_locator,
                content_hash=normalized.content_hash,
            )
            if evidence is None:
                evidence = EvidenceRecord(
                    id=uuid4(),
                    instrument_id=None,
                    evidence_type="MARKET",
                    source_name=preview.source.source_name,
                    source_locator=preview.source.source_locator,
                    source_tier="OTHER",
                    observed_at=preview.source.observed_at,
                    effective_at=preview.source.effective_at,
                    available_at=preview.source.available_at,
                    ingested_at=now,
                    expires_at=None,
                    quality_score=normalized.quality_score,
                    freshness_status=normalized.freshness_status.value,
                    payload_json=payload,
                    content_hash=normalized.content_hash,
                    **{
                        **common(command.request_id),
                        "metadata_json": {
                            "provider": PROVIDER,
                            "source_schema_version": "universe-source-csv-v1",
                        },
                    },
                )
                await uow.evidence.append(evidence)
                await uow.research_artifacts.append(
                    ResearchArtifactRecord(
                        provider=PROVIDER,
                        provider_ref=preview.file_hash,
                        artifact_type="MARKET",
                        as_of=preview.source.available_at,
                        raw_payload_ref=preview.source.source_locator,
                        normalized_payload_json=payload,
                        content_hash=normalized.content_hash,
                        **common(command.request_id),
                    )
                )
            snapshot = UniverseSnapshot(
                snapshot_id=command.request_id,
                source=preview.source,
                members=preview.members,
                ingested_at=now,
                evidence_id=evidence.id,
                file_hash=preview.file_hash,
                members_hash=preview.members_hash,
                content_hash="0" * 64,
                member_count=len(preview.members),
            )
            snapshot = snapshot.model_copy(
                update={
                    "content_hash": fingerprint(
                        snapshot.model_dump(mode="json", exclude={"content_hash"})
                    )
                }
            )
            uow.session.add(
                UniverseSnapshotRecord(
                    id=snapshot.snapshot_id,
                    request_hash=fingerprint(command.model_dump(mode="json")),
                    source_json=snapshot.source.model_dump(mode="json"),
                    ingested_at=now,
                    evidence_id=evidence.id,
                    file_hash=snapshot.file_hash,
                    members_hash=snapshot.members_hash,
                    content_hash=snapshot.content_hash,
                    member_count=snapshot.member_count,
                    **common(command.request_id),
                )
            )
            await uow.session.flush()
            uow.session.add_all(
                [
                    UniverseMemberRecord(
                        snapshot_id=snapshot.snapshot_id,
                        **m.model_dump(exclude={"schema_version"}),
                    )
                    for m in snapshot.members
                ]
            )
            await emit(
                uow,
                "universe.snapshot.imported",
                snapshot.snapshot_id,
                {
                    "snapshot_hash": snapshot.content_hash,
                    "preview_hash": preview.preview_hash,
                    "command_hash": fingerprint(command.model_dump(mode="json")),
                    "origin": "SOURCE_DECLARED",
                    "verification": "UNVERIFIED",
                },
                now,
            )
            await uow.commit()
            return snapshot

    async def _origin(self, session: AsyncSession, run_id: UUID) -> UniverseOrigin | None:
        record = await session.scalar(
            select(UniverseRunRecord).where(UniverseRunRecord.run_id == run_id)
        )
        if record is None:
            return None
        snapshot = await self._snapshot(session, record.snapshot_id)
        try:
            run = await self.funnels.get_run(run_id)
        except OpportunityError:
            raise UniverseError("UNIVERSE_ORIGIN_INVALID") from None
        event = await session.get(EventLogRecord, record.run_event_id)
        if (
            run is None
            or event is None
            or event.aggregate_id != run_id
            or event.aggregate_type != "opportunity_funnel_run"
            or record.snapshot_hash != snapshot.content_hash
            or run.query.scope_name != snapshot.source.source_name
            or run.query.as_of
            < max(
                snapshot.source.observed_at,
                snapshot.source.effective_at,
                snapshot.source.available_at,
                snapshot.ingested_at,
            )
            or set(run.query.instrument_ids) != {m.instrument_id for m in snapshot.members}
            or run.query.scope_locator
            != f"universe_snapshot:{snapshot.snapshot_id}:{snapshot.content_hash}"
        ):
            raise UniverseError("UNIVERSE_ORIGIN_INVALID")
        return UniverseOrigin(run_id=run_id, source=summary(snapshot))

    async def origin(self, run_id: UUID) -> UniverseOrigin | None:
        async with self.sessions() as session:
            return await self._origin(session, run_id)

    async def replay_run(self, snapshot_id: UUID, command: UniverseRun) -> UniverseBoundRun | None:
        async with self.sessions() as session:
            record = await session.scalar(
                select(UniverseRunRecord).where(UniverseRunRecord.run_id == command.request_id)
            )
            if record is None:
                return None
            expected = fingerprint(
                {"snapshot_id": str(snapshot_id), **command.model_dump(mode="json")}
            )
            if record.request_hash != expected:
                raise UniverseError("REQUEST_CONTENT_CONFLICT")
            origin = await self._origin(session, command.request_id)
            run = await self.funnels.get_run(command.request_id)
            if origin is None or run is None:
                raise UniverseError("UNIVERSE_ORIGIN_INVALID")
            return UniverseBoundRun(origin=origin, run=run)

    async def save_run(
        self, snapshot: UniverseSnapshot, command: UniverseRun, run: FunnelRun
    ) -> UniverseBoundRun:
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            await lock(uow.session, "opportunity-funnel-run", command.request_id)
            existing = await uow.session.scalar(
                select(UniverseRunRecord).where(UniverseRunRecord.run_id == command.request_id)
            )
            expected = fingerprint(
                {"snapshot_id": str(snapshot.snapshot_id), **command.model_dump(mode="json")}
            )
            if existing:
                if existing.request_hash != expected:
                    raise UniverseError("REQUEST_CONTENT_CONFLICT")
                origin = await self._origin(uow.session, command.request_id)
                old = await self.funnels.get_run(command.request_id)
                if origin is None or old is None:
                    raise UniverseError("UNIVERSE_ORIGIN_INVALID")
                return UniverseBoundRun(origin=origin, run=old)
            old_event = await uow.session.scalar(
                select(EventLogRecord).where(
                    EventLogRecord.aggregate_type == "opportunity_funnel_run",
                    EventLogRecord.aggregate_id == command.request_id,
                )
            )
            if old_event is not None:
                raise UniverseError("REQUEST_CONTENT_CONFLICT")
            persisted = await self._snapshot(uow.session, snapshot.snapshot_id)
            if persisted != snapshot or set(run.query.instrument_ids) != {
                m.instrument_id for m in persisted.members
            }:
                raise UniverseError("UNIVERSE_SNAPSHOT_CONFLICT")
            await self.funnels.save_run_in(uow, run)
            event_id = await uow.session.scalar(
                select(EventLogRecord.id).where(
                    EventLogRecord.aggregate_type == "opportunity_funnel_run",
                    EventLogRecord.aggregate_id == command.request_id,
                )
            )
            if event_id is None:
                raise UniverseError("UNIVERSE_ORIGIN_INVALID")
            uow.session.add(
                UniverseRunRecord(
                    snapshot_id=snapshot.snapshot_id,
                    snapshot_hash=snapshot.content_hash,
                    run_id=run.run_id,
                    run_event_id=event_id,
                    request_hash=expected,
                    **common(command.request_id),
                )
            )
            await emit(
                uow,
                "universe.funnel.bound",
                run.run_id,
                {
                    "snapshot_id": str(snapshot.snapshot_id),
                    "snapshot_hash": snapshot.content_hash,
                    "run_id": str(run.run_id),
                    "command": command.model_dump(mode="json"),
                },
                run.ingested_at,
            )
            await uow.commit()
            return UniverseBoundRun(
                origin=UniverseOrigin(run_id=run.run_id, source=summary(snapshot)), run=run
            )
