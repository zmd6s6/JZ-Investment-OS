"""Independent monthly commands, CAS receipts and verified immutable report reads."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.daily_runtime import DailyMode, DailyTask
from investment_os.application.monthly_review import (
    MonthlyConfiguration,
    MonthlyError,
    MonthlyPrepared,
    MonthlyReport,
    MonthlyReportHistory,
    MonthlySave,
)
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.infrastructure.daily_runtime_store import lock
from investment_os.infrastructure.monthly_review_models import (
    MonthlyAuthorizationRecord,
    MonthlyConfigurationRecord,
    MonthlyMemberRecord,
    MonthlyReportRecord,
)
from investment_os.infrastructure.monthly_review_scope import capture, prepared_hash
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    EventLogRecord,
    OutboxEventRecord,
    TaskRunRecord,
)


def common(identifier: UUID) -> dict[str, Any]:
    return dict(
        created_by="monthly_review",
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
        aggregate_type="MonthlyReview",
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
            payload_json={"event_id": str(event.id), "monthly_id": str(identifier)},
            published_at=None,
            attempts=0,
            last_error=None,
            **common(identifier),
        )
    )
    session.add(
        AuditLogRecord(
            actor_type="HUMAN" if kind == "monthly.command" else "SYSTEM",
            actor_id="monthly_api_or_worker",
            operation=kind,
            entity_type="MonthlyReview",
            entity_id=identifier,
            before_hash=None,
            after_hash=fingerprint(payload),
            ip_or_runtime_ref="local_api_or_worker",
            occurred_at=now,
            **common(identifier),
        )
    )


async def configuration(
    session: AsyncSession, pointer: MonthlyConfigurationRecord, now: datetime
) -> MonthlyConfiguration:
    record = await session.get(MonthlyAuthorizationRecord, pointer.revision_id)
    if record is None or record.schedule_id != pointer.id:
        raise MonthlyError("MONTHLY_AUTHORIZATION_REFERENCE_INVALID")
    try:
        prepared = MonthlyPrepared.model_validate(record.prepared_json)
    except ValueError:
        raise MonthlyError("MONTHLY_AUTHORIZATION_SCHEMA_INVALID") from None
    members = set(
        await session.scalars(
            select(MonthlyMemberRecord.instrument_id).where(
                MonthlyMemberRecord.revision_id == record.id
            )
        )
    )
    command = prepared.command
    if (
        prepared_hash(prepared) != record.content_hash
        or prepared.content_hash != record.content_hash
        or command.schedule_id != pointer.id
        or command.portfolio_id != record.portfolio_id
        or command.calendar_import_id != record.calendar_import_id
        or command.market != record.market
        or command.coverage_start != record.coverage_start
        or command.coverage_end != record.coverage_end
        or command.valid_from != record.valid_from
        or command.valid_until != record.valid_until
        or members != set(command.portfolio_instrument_ids)
        or {member.instrument_id for member in prepared.members} != members
    ):
        raise MonthlyError("MONTHLY_AUTHORIZATION_HASH_OR_RELATION_INVALID")
    blocker = (
        "MONTHLY_REVOKED"
        if pointer.revoked
        else "MONTHLY_PAUSED"
        if not pointer.enabled
        else "MONTHLY_AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID"
        if not command.valid_from <= now < command.valid_until
        else None
    )
    return MonthlyConfiguration(
        schedule_id=pointer.id,
        revision_id=record.id,
        version=pointer.version,
        enabled=pointer.enabled,
        revoked=pointer.revoked,
        prepared=prepared,
        blocker=blocker,
    )


def verify_report(record: MonthlyReportRecord, now: datetime) -> MonthlyReport:
    try:
        report = MonthlyReport.model_validate(record.report_json)
        report.verify()
    except ValueError:
        raise MonthlyError("MONTHLY_REPORT_SCHEMA_OR_HASH_INVALID") from None
    if (
        report.content_hash != record.content_hash
        or report.report_id != record.id
        or report.task_run_id != record.task_run_id
        or report.schedule_id != record.schedule_id
        or report.revision_id != record.revision_id
        or report.period_start != record.period_start
        or report.period_end != record.period_end
        or report.business_as_of != record.business_as_of
        or report.knowledge_as_of != record.knowledge_as_of
        or report.usable_until != record.usable_until
        or report.authorization_version != record.authorization_version
    ):
        raise MonthlyError("MONTHLY_REPORT_RELATION_INVALID")
    if now >= report.usable_until:
        raise MonthlyError("MONTHLY_REPORT_EXPIRED_HISTORY_PRESERVED")
    return report


class SqlMonthlyReview:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def preview(self, command: MonthlySave, now: datetime) -> MonthlyPrepared:
        async with self.sessions() as session:
            prepared, _ = await capture(session, command, now, lock=False)
            return prepared

    async def _receipt(
        self, session: AsyncSession, identifier: UUID, payload: dict[str, Any]
    ) -> MonthlyConfiguration | None:
        record = await session.scalar(
            select(EventLogRecord).where(
                EventLogRecord.event_type == "monthly.command",
                EventLogRecord.aggregate_id == identifier,
            )
        )
        if record is None:
            return None
        if record.payload_json.get("command_hash") != fingerprint(payload):
            raise MonthlyError("MONTHLY_REQUEST_CONTENT_CONFLICT")
        try:
            return MonthlyConfiguration.model_validate(record.payload_json["result"])
        except (KeyError, ValueError):
            raise MonthlyError("MONTHLY_COMMAND_RECEIPT_INVALID") from None

    async def save(self, command: MonthlySave, preview_hash: str) -> MonthlyConfiguration:
        payload = {
            "kind": "SAVE",
            "command": command.model_dump(mode="json"),
            "preview_hash": preview_hash,
        }
        async with self.sessions() as session, session.begin():
            await lock(session, "monthly-command", command.request_id)
            prior = await self._receipt(session, command.request_id, payload)
            if prior:
                return prior
            await lock(session, "monthly-configuration", command.schedule_id)
            pointer = await session.get(
                MonthlyConfigurationRecord, command.schedule_id, with_for_update=True
            )
            if pointer and pointer.revoked:
                raise MonthlyError("MONTHLY_REVOKED")
            if (pointer.version if pointer else 0) != command.expected_version:
                raise MonthlyError("MONTHLY_VERSION_CONFLICT")
            prepared, _ = await capture(session, command, datetime.now(UTC), lock=True)
            if prepared.content_hash != preview_hash:
                raise MonthlyError("MONTHLY_PREVIEW_STALE_REFRESH_AND_CONFIRM")
            revision_id = uuid4()
            if pointer is None:
                pointer = MonthlyConfigurationRecord(
                    id=command.schedule_id,
                    revision_id=revision_id,
                    version=1,
                    enabled=False,
                    revoked=False,
                    **common(command.request_id),
                )
                session.add(pointer)
            else:
                pointer.revision_id, pointer.version, pointer.enabled = (
                    revision_id,
                    pointer.version + 1,
                    False,
                )
            await session.flush()
            session.add(
                MonthlyAuthorizationRecord(
                    id=revision_id,
                    schedule_id=pointer.id,
                    portfolio_id=command.portfolio_id,
                    calendar_import_id=command.calendar_import_id,
                    market=command.market,
                    coverage_start=command.coverage_start,
                    coverage_end=command.coverage_end,
                    valid_from=command.valid_from,
                    valid_until=command.valid_until,
                    prepared_json=prepared.model_dump(mode="json"),
                    content_hash=prepared.content_hash,
                    **common(command.request_id),
                )
            )
            await session.flush()
            session.add_all(
                [
                    MonthlyMemberRecord(revision_id=revision_id, instrument_id=member.instrument_id)
                    for member in prepared.members
                ]
            )
            await session.flush()
            result = await configuration(session, pointer, datetime.now(UTC))
            await emit(
                session,
                "monthly.command",
                command.request_id,
                dict(command_hash=fingerprint(payload), result=result.model_dump(mode="json")),
                datetime.now(UTC),
            )
            return result

    async def mode(self, schedule_id: UUID, command: DailyMode) -> MonthlyConfiguration:
        payload = {
            "kind": "MODE",
            "schedule_id": str(schedule_id),
            **command.model_dump(mode="json"),
        }
        async with self.sessions() as session, session.begin():
            await lock(session, "monthly-command", command.request_id)
            prior = await self._receipt(session, command.request_id, payload)
            if prior:
                return prior
            await lock(session, "monthly-configuration", schedule_id)
            pointer = await session.get(
                MonthlyConfigurationRecord, schedule_id, with_for_update=True
            )
            if pointer is None:
                raise MonthlyError("MONTHLY_CONFIGURATION_NOT_FOUND")
            if pointer.revoked:
                raise MonthlyError("MONTHLY_REVOKED")
            if pointer.version != command.expected_version:
                raise MonthlyError("MONTHLY_VERSION_CONFLICT")
            current = await configuration(session, pointer, datetime.now(UTC))
            if command.action == "ENABLE":
                prepared, _ = await capture(
                    session, current.prepared.command, datetime.now(UTC), lock=True
                )
                if prepared.content_hash != current.prepared.content_hash:
                    raise MonthlyError("MONTHLY_SCOPE_OR_CALENDAR_CHANGED")
                # Recheck time after all awaited capture before the write.
                if (
                    not prepared.command.valid_from
                    <= datetime.now(UTC)
                    < prepared.command.valid_until
                ):
                    raise MonthlyError("MONTHLY_AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID")
            pointer.version += 1
            pointer.enabled = command.action == "ENABLE"
            pointer.revoked = command.action == "REVOKE"
            result = await configuration(session, pointer, datetime.now(UTC))
            await emit(
                session,
                "monthly.command",
                command.request_id,
                dict(command_hash=fingerprint(payload), result=result.model_dump(mode="json")),
                datetime.now(UTC),
            )
            return result

    async def configurations(self) -> tuple[MonthlyConfiguration, ...]:
        result = []
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(MonthlyConfigurationRecord)
                    .order_by(MonthlyConfigurationRecord.created_at.desc())
                    .limit(50)
                )
            ).all()
            for pointer in rows:
                config = await configuration(session, pointer, datetime.now(UTC))
                if config.blocker is None:
                    try:
                        prepared, _ = await capture(
                            session, config.prepared.command, datetime.now(UTC), lock=False
                        )
                        if prepared.content_hash != config.prepared.content_hash:
                            raise MonthlyError("MONTHLY_SCOPE_OR_CALENDAR_CHANGED")
                    except MonthlyError as exc:
                        config = config.model_copy(update={"blocker": exc.code})
                result.append(config)
        return tuple(result)

    async def reports(self, schedule_id: UUID | None = None) -> tuple[MonthlyReport, ...]:
        statement = select(MonthlyReportRecord).where(
            MonthlyReportRecord.usable_until > datetime.now(UTC)
        )
        if schedule_id:
            statement = statement.where(MonthlyReportRecord.schedule_id == schedule_id)
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    statement.order_by(MonthlyReportRecord.recorded_at.desc()).limit(60)
                )
            ).all()
            return tuple(verify_report(row, datetime.now(UTC)) for row in rows)

    async def replay(self, report_id: UUID) -> MonthlyReport:
        async with self.sessions() as session:
            record = await session.get(MonthlyReportRecord, report_id)
            if record is None:
                raise MonthlyError("MONTHLY_REPORT_NOT_FOUND")
            return verify_report(record, datetime.now(UTC))

    async def history(self) -> tuple[MonthlyReportHistory, ...]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(MonthlyReportRecord)
                    .order_by(MonthlyReportRecord.recorded_at.desc())
                    .limit(60)
                )
            ).all()
            return tuple(
                MonthlyReportHistory(
                    report_id=row.id,
                    schedule_id=row.schedule_id,
                    period_start=row.period_start,
                    period_end=row.period_end,
                    recorded_at=row.recorded_at,
                    usable_until=row.usable_until,
                    content_hash=row.content_hash,
                    usable=datetime.now(UTC) < row.usable_until,
                )
                for row in rows
            )

    async def runs(self) -> tuple[DailyTask, ...]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(TaskRunRecord)
                    .where(TaskRunRecord.task_name == "monthly_portfolio_review")
                    .order_by(TaskRunRecord.started_at.desc())
                    .limit(60)
                )
            ).all()
            # TaskRun logical keys bind schedule/revision/month even on rolled-back failures.
            return tuple(
                DailyTask(
                    task_run_id=row.id,
                    schedule_id=UUID(row.idempotency_key.split(":")[1]),
                    status=row.status,
                    attempt=row.attempt,
                    started_at=row.started_at,
                    finished_at=row.finished_at,
                    error_code=row.error_json.get("code") if row.error_json else None,
                )
                for row in rows
            )
