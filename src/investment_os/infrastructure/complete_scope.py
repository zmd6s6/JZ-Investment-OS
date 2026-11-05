"""Durable whole-snapshot scans using existing append-only origin and event records."""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from investment_os.application.complete_scope import (
    CompleteScopeCommand,
    CompleteScopeRun,
    validate_complete_snapshot,
)
from investment_os.application.universe_snapshots import (
    UniverseError,
    UniverseSnapshot,
    fingerprint,
)
from investment_os.infrastructure.persistence.models import EventLogRecord
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork
from investment_os.infrastructure.universe_models import UniverseRunRecord
from investment_os.infrastructure.universe_snapshots import SqlUniverseSnapshots, common, emit, lock

KIND = "opportunity_complete_scope_v2"


def request_hash(snapshot_id: UUID, command: CompleteScopeCommand) -> str:
    return fingerprint({"snapshot_id": str(snapshot_id), **command.model_dump(mode="json")})


class SqlCompleteScope(SqlUniverseSnapshots):
    async def _read_complete(
        self, session: AsyncSession, record: UniverseRunRecord
    ) -> CompleteScopeRun:
        snapshot = await self._snapshot(session, record.snapshot_id)
        event = await session.get(EventLogRecord, record.run_event_id)
        try:
            if (
                event is None
                or event.aggregate_type != KIND
                or event.aggregate_id != record.run_id
                or record.snapshot_hash != snapshot.content_hash
                or event.payload_json["snapshot_hash"] != fingerprint(event.payload_json["run"])
            ):
                raise ValueError("invalid event")
            run = CompleteScopeRun.model_validate(event.payload_json["run"])
            if (
                run.command.request_id != record.run_id
                or record.request_hash != request_hash(record.snapshot_id, run.command)
                or event.payload_json["request_hash"] != record.request_hash
            ):
                raise ValueError("invalid identity")
            validate_complete_snapshot(snapshot, run)
            return run
        except (ValueError, TypeError, KeyError):
            raise UniverseError("COMPLETE_SCOPE_INVALID") from None

    async def get_complete(self, run_id: UUID) -> CompleteScopeRun | None:
        async with self.sessions() as session:
            record = await session.scalar(
                select(UniverseRunRecord).where(UniverseRunRecord.run_id == run_id)
            )
            if record is None:
                return None
            return await self._read_complete(session, record)

    async def replay_complete(
        self, snapshot_id: UUID, command: CompleteScopeCommand
    ) -> CompleteScopeRun | None:
        async with self.sessions() as session:
            record = await session.scalar(
                select(UniverseRunRecord).where(UniverseRunRecord.run_id == command.request_id)
            )
            if record is None:
                return None
            if record.request_hash != request_hash(snapshot_id, command):
                raise UniverseError("REQUEST_CONTENT_CONFLICT")
            return await self._read_complete(session, record)

    async def save_complete(
        self, snapshot: UniverseSnapshot, command: CompleteScopeCommand, run: CompleteScopeRun
    ) -> CompleteScopeRun:
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            await lock(uow.session, "opportunity-funnel-run", command.request_id)
            existing = await uow.session.scalar(
                select(UniverseRunRecord).where(UniverseRunRecord.run_id == command.request_id)
            )
            expected = request_hash(snapshot.snapshot_id, command)
            if existing is not None:
                if existing.request_hash != expected:
                    raise UniverseError("REQUEST_CONTENT_CONFLICT")
                return await self._read_complete(uow.session, existing)
            old_event = await uow.session.scalar(
                select(EventLogRecord.id).where(
                    EventLogRecord.aggregate_type.in_(["opportunity_funnel_run", KIND]),
                    EventLogRecord.aggregate_id == command.request_id,
                )
            )
            if old_event is not None:
                raise UniverseError("REQUEST_CONTENT_CONFLICT")
            persisted = await self._snapshot(uow.session, snapshot.snapshot_id)
            if persisted != snapshot or run.command != command:
                raise UniverseError("UNIVERSE_SNAPSHOT_CONFLICT")
            validate_complete_snapshot(persisted, run)
            raw = run.model_dump(mode="json")
            event = EventLogRecord(
                id=uuid4(),
                event_type="opportunity.complete_scope.recorded",
                aggregate_type=KIND,
                aggregate_id=command.request_id,
                occurred_at=run.ingested_at,
                payload_json={
                    "request_hash": expected,
                    "snapshot_hash": fingerprint(raw),
                    "run": raw,
                },
                **common(command.request_id),
            )
            await uow.events.append(event)
            await uow.session.flush()
            uow.session.add(
                UniverseRunRecord(
                    snapshot_id=snapshot.snapshot_id,
                    snapshot_hash=snapshot.content_hash,
                    run_id=command.request_id,
                    run_event_id=event.id,
                    request_hash=expected,
                    **common(command.request_id),
                )
            )
            await emit(
                uow,
                "universe.complete_scope.bound",
                command.request_id,
                {
                    "snapshot_id": str(snapshot.snapshot_id),
                    "snapshot_hash": snapshot.content_hash,
                    "run_id": str(command.request_id),
                    "command": command.model_dump(mode="json"),
                },
                run.ingested_at,
            )
            await uow.commit()
            return run
