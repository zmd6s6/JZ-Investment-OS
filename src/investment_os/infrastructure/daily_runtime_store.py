"""Versioned daily configuration commands and strict persisted snapshot reads."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.daily_runtime import (
    DailyConfiguration,
    DailyError,
    DailyMode,
    DailyPrepared,
    DailySave,
)
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.infrastructure.daily_runtime_models import (
    DailyAuthorizationRecord,
    DailyConfigurationRecord,
    DailyMemberRecord,
)
from investment_os.infrastructure.daily_runtime_setup import (
    SqlDailySetup,
    capture_calendar,
    capture_scope,
)
from investment_os.infrastructure.persistence.locks import advisory_lock_key
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    EventLogRecord,
    OutboxEventRecord,
)


async def lock(session: AsyncSession, namespace: str, identifier: UUID | str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": advisory_lock_key(namespace, str(identifier))},
    )


def common(identifier: UUID) -> dict[str, Any]:
    return dict(
        created_by="daily_runtime",
        correlation_id=identifier,
        causation_id=None,
        schema_version="1.0",
        metadata_json={},
    )


async def emit(
    session: AsyncSession, kind: str, identifier: UUID, payload: dict[str, Any], now: datetime
) -> None:
    event = EventLogRecord(
        event_type=kind,
        aggregate_type="DailyRuntime",
        aggregate_id=identifier,
        payload_json=payload,
        occurred_at=now,
        **common(identifier),
    )
    session.add(event)
    await session.flush()
    session.add(
        OutboxEventRecord(
            event_id=event.id,
            topic=kind,
            payload_json={"event_id": str(event.id), "daily_id": str(identifier)},
            published_at=None,
            attempts=0,
            last_error=None,
            **common(identifier),
        )
    )
    session.add(
        AuditLogRecord(
            actor_type="HUMAN" if kind == "daily.command" else "SYSTEM",
            actor_id="daily_local_api" if kind == "daily.command" else "daily_worker",
            operation=kind,
            entity_type="DailyRuntime",
            entity_id=identifier,
            before_hash=None,
            after_hash=fingerprint(payload),
            ip_or_runtime_ref="local_api_or_worker",
            occurred_at=now,
            **common(identifier),
        )
    )


async def read_prepared(session: AsyncSession, config: DailyConfigurationRecord) -> DailyPrepared:
    record = await session.get(DailyAuthorizationRecord, config.revision_id)
    if record is None or record.schedule_id != config.id:
        raise DailyError("DAILY_AUTHORIZATION_SNAPSHOT_INVALID")
    try:
        prepared = DailyPrepared.model_validate(record.prepared_json)
    except ValueError:
        raise DailyError("DAILY_AUTHORIZATION_SNAPSHOT_INVALID") from None
    value = prepared.command
    members = (
        await session.scalars(
            select(DailyMemberRecord).where(DailyMemberRecord.revision_id == record.id)
        )
    ).all()
    if (
        prepared.input_hash != record.content_hash
        or fingerprint(prepared.model_dump(mode="json", exclude={"input_hash"}))
        != prepared.input_hash
        or value.schedule_id != config.id
        or value.mode != record.mode
        or value.market != record.market
        or value.portfolio_id != record.portfolio_id
        or value.calendar_import_id != record.calendar_import_id
        or prepared.calendar_hash != record.calendar_hash
        or value.coverage_start != record.coverage_start
        or value.coverage_end != record.coverage_end
        or value.valid_from != record.valid_from
        or value.valid_until != record.valid_until
        or value.retention_days != record.retention_days
        or {(m.instrument_id, m.in_portfolio, m.in_watchlist) for m in members}
        != {(m.instrument_id, m.in_portfolio, m.in_watchlist) for m in prepared.members}
    ):
        raise DailyError("DAILY_AUTHORIZATION_SNAPSHOT_INVALID")
    return prepared


async def configuration(
    session: AsyncSession, record: DailyConfigurationRecord
) -> DailyConfiguration:
    prepared = await read_prepared(session, record)
    return DailyConfiguration(
        schedule_id=record.id,
        revision_id=record.revision_id,
        version=record.version,
        enabled=record.enabled,
        revoked=record.revoked,
        enabled_since=record.enabled_since,
        prepared=prepared,
        blocker="DAILY_AUTHORIZATION_REVOKED"
        if record.revoked
        else "DAILY_PAUSED"
        if not record.enabled
        else None,
    )


class SqlDailyRuntimeStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], setup: SqlDailySetup):
        self.sessions, self.setup = sessions, setup

    async def _replay(
        self, session: AsyncSession, request_id: UUID, command: dict[str, Any]
    ) -> DailyConfiguration | None:
        receipt = await session.scalar(
            select(EventLogRecord).where(
                EventLogRecord.event_type == "daily.command",
                EventLogRecord.aggregate_id == request_id,
            )
        )
        if receipt is None:
            return None
        if receipt.payload_json.get("command_hash") != fingerprint(command):
            raise DailyError("DAILY_REQUEST_CONTENT_CONFLICT")
        try:
            return DailyConfiguration.model_validate(receipt.payload_json["result"])
        except (KeyError, ValueError):
            raise DailyError("DAILY_RECEIPT_INVALID") from None

    async def replay_save(self, command: DailySave) -> DailyConfiguration | None:
        async with self.sessions() as session:
            return await self._replay(
                session, command.request_id, {"kind": "SAVE", **command.model_dump(mode="json")}
            )

    async def save(self, prepared: DailyPrepared) -> DailyConfiguration:
        command = prepared.command
        payload = {"kind": "SAVE", **command.model_dump(mode="json")}
        async with self.sessions() as session, session.begin():
            await lock(session, "daily-command", command.request_id)
            prior = await self._replay(session, command.request_id, payload)
            if prior:
                return prior
            await lock(session, "daily-configuration", command.schedule_id)
            record = await session.get(
                DailyConfigurationRecord, command.schedule_id, with_for_update=True
            )
            if (record.version if record else 0) != command.expected_version:
                raise DailyError("DAILY_VERSION_CONFLICT")
            if prepared.input_hash != fingerprint(
                prepared.model_dump(mode="json", exclude={"input_hash"})
            ):
                raise DailyError("DAILY_PREPARED_HASH_INVALID")
            # Recheck identity/calendar after acquiring configuration ownership, before writes.
            if await capture_scope(session, command, lock=True) != prepared.members:
                raise DailyError("DAILY_SCOPE_CHANGED_DURING_CONFIRMATION")
            calendar, _ = await capture_calendar(session, command, lock=True)
            if calendar.content_hash != prepared.calendar_hash:
                raise DailyError("DAILY_CALENDAR_CHANGED_OR_MISSING")
            await self.setup.verify_profiles(prepared, datetime.now(UTC))
            revision_id = uuid4()
            if record is None:
                record = DailyConfigurationRecord(
                    id=command.schedule_id,
                    revision_id=revision_id,
                    version=1,
                    enabled=False,
                    revoked=False,
                    enabled_since=None,
                    **common(command.request_id),
                )
                session.add(record)
            else:
                record.revision_id = revision_id
                record.version += 1
                record.enabled = False
                record.revoked = False
                record.enabled_since = None
            await session.flush()  # Deferred revision FK allows this explicit circular aggregate.
            session.add(
                DailyAuthorizationRecord(
                    id=revision_id,
                    schedule_id=record.id,
                    mode=command.mode,
                    market=command.market,
                    portfolio_id=command.portfolio_id,
                    calendar_import_id=command.calendar_import_id,
                    calendar_hash=prepared.calendar_hash,
                    coverage_start=command.coverage_start,
                    coverage_end=command.coverage_end,
                    valid_from=command.valid_from,
                    valid_until=command.valid_until,
                    retention_days=command.retention_days,
                    prepared_json=prepared.model_dump(mode="json"),
                    content_hash=prepared.input_hash,
                    **common(command.request_id),
                )
            )
            await session.flush()
            session.add_all(
                [
                    DailyMemberRecord(
                        revision_id=revision_id,
                        instrument_id=m.instrument_id,
                        in_portfolio=m.in_portfolio,
                        in_watchlist=m.in_watchlist,
                    )
                    for m in prepared.members
                ]
            )
            await session.flush()
            result = await configuration(session, record)
            await emit(
                session,
                "daily.command",
                command.request_id,
                {
                    "command_hash": fingerprint(payload),
                    "command": payload,
                    "result": result.model_dump(mode="json"),
                },
                datetime.now(UTC),
            )
            return result

    async def mode(self, schedule_id: UUID, command: DailyMode) -> DailyConfiguration:
        payload = {
            "kind": "MODE",
            "schedule_id": str(schedule_id),
            **command.model_dump(mode="json"),
        }
        async with self.sessions() as session, session.begin():
            await lock(session, "daily-command", command.request_id)
            prior = await self._replay(session, command.request_id, payload)
            if prior:
                return prior
            await lock(session, "daily-configuration", schedule_id)
            record = await session.get(DailyConfigurationRecord, schedule_id, with_for_update=True)
            if record is None:
                raise DailyError("DAILY_CONFIGURATION_NOT_FOUND")
            if record.version != command.expected_version:
                raise DailyError("DAILY_VERSION_CONFLICT")
            prepared = await read_prepared(session, record)
            now = datetime.now(UTC)
            if command.action == "ENABLE":
                if record.revoked:
                    raise DailyError("DAILY_AUTHORIZATION_REVOKED")
                if not prepared.command.valid_from <= now < prepared.command.valid_until:
                    raise DailyError("DAILY_AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID")
                if await capture_scope(session, prepared.command, lock=True) != prepared.members:
                    raise DailyError("DAILY_SCOPE_CHANGED")
                calendar, _ = await capture_calendar(session, prepared.command, lock=True)
                if calendar.content_hash != prepared.calendar_hash:
                    raise DailyError("DAILY_CALENDAR_CHANGED_OR_MISSING")
                await self.setup.verify_profiles(prepared, now)
                record.enabled = True
                record.enabled_since = now
            else:
                record.enabled = False
                record.enabled_since = None
                if command.action == "REVOKE":
                    record.revoked = True
            record.version += 1
            await session.flush()
            result = await configuration(session, record)
            await emit(
                session,
                "daily.command",
                command.request_id,
                {
                    "command_hash": fingerprint(payload),
                    "command": payload,
                    "result": result.model_dump(mode="json"),
                },
                now,
            )
            return result

    async def configurations(self) -> tuple[DailyConfiguration, ...]:
        async with self.sessions() as session:
            records = (
                await session.scalars(
                    select(DailyConfigurationRecord)
                    .order_by(
                        DailyConfigurationRecord.created_at.desc(), DailyConfigurationRecord.id
                    )
                    .limit(50)
                )
            ).all()
            return tuple([await configuration(session, record) for record in records])
