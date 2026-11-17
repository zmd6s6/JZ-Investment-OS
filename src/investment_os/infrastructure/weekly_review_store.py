"""Independent weekly commands, CAS receipts and verified immutable report reads."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.daily_runtime import DailyMode, DailyTask
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.application.weekly_review import (
    WeeklyConfiguration,
    WeeklyError,
    WeeklyPrepared,
    WeeklyReport,
    WeeklyReportHistory,
    WeeklySave,
)
from investment_os.infrastructure.daily_runtime_store import lock
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    EventLogRecord,
    OutboxEventRecord,
    TaskRunRecord,
)
from investment_os.infrastructure.weekly_review_models import (
    WeeklyAuthorizationRecord,
    WeeklyCalendarDayRecord,
    WeeklyConfigurationRecord,
    WeeklyMemberRecord,
    WeeklyReportEvidenceRecord,
    WeeklyReportRecord,
    WeeklyReportReferenceRecord,
)
from investment_os.infrastructure.weekly_review_scope import capture, prepared_hash


def common(identifier: UUID) -> dict[str, Any]:
    return dict(
        created_by="weekly_review",
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
        aggregate_type="WeeklyReview",
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
            payload_json={"event_id": str(event.id), "weekly_id": str(identifier)},
            published_at=None,
            attempts=0,
            last_error=None,
            **common(identifier),
        )
    )
    session.add(
        AuditLogRecord(
            actor_type="HUMAN" if kind == "weekly.command" else "SYSTEM",
            actor_id="weekly_api_or_worker",
            operation=kind,
            entity_type="WeeklyReview",
            entity_id=identifier,
            before_hash=None,
            after_hash=fingerprint(payload),
            ip_or_runtime_ref="local_api_or_worker",
            occurred_at=now,
            **common(identifier),
        )
    )


async def configuration(
    session: AsyncSession, pointer: WeeklyConfigurationRecord, now: datetime
) -> WeeklyConfiguration:
    record = (
        await session.get(WeeklyAuthorizationRecord, pointer.revision_id)
        if pointer.revision_id is not None
        else None
    )
    # 0027 rows are retained, never reinterpreted as a new complete authorization.
    # Their real pointer/CAS state remains visible and may be paused/revoked, but
    # neither an old JSON shape nor a missing revision can authorize execution.
    if pointer.created_by == "weekly_legacy" and (
        record is None or record.created_by == "weekly_legacy"
    ):
        return WeeklyConfiguration(
            schedule_id=pointer.id,
            revision_id=pointer.revision_id,
            version=pointer.version,
            enabled=pointer.enabled,
            revoked=pointer.revoked,
            prepared=None,
            blocker="WEEKLY_LEGACY_UNVERIFIED_CREATE_NEW_AUTHORIZATION",
        )
    if record is None or record.schedule_id != pointer.id:
        raise WeeklyError("WEEKLY_AUTHORIZATION_REFERENCE_INVALID")
    try:
        prepared = WeeklyPrepared.model_validate(record.prepared_json)
    except ValueError:
        raise WeeklyError("WEEKLY_AUTHORIZATION_SCHEMA_INVALID") from None
    members = set(
        await session.scalars(
            select(WeeklyMemberRecord.instrument_id).where(
                WeeklyMemberRecord.revision_id == record.id
            )
        )
    )
    days = (
        await session.scalars(
            select(WeeklyCalendarDayRecord).where(WeeklyCalendarDayRecord.revision_id == record.id)
        )
    ).all()
    if {day.business_date: day.state for day in days} != prepared.command.calendar_days:
        raise WeeklyError("WEEKLY_PERSISTED_CALENDAR_MANIFEST_INVALID")
    roles = set(
        (
            await session.execute(
                select(WeeklyMemberRecord.instrument_id, WeeklyMemberRecord.membership).where(
                    WeeklyMemberRecord.revision_id == record.id
                )
            )
        ).all()
    )
    expected_roles = {
        (identifier, "PORTFOLIO") for identifier in prepared.command.portfolio_instrument_ids
    } | {(identifier, "WATCHLIST") for identifier in prepared.command.watchlist_instrument_ids}
    if roles != expected_roles:
        raise WeeklyError("WEEKLY_PERSISTED_MEMBERSHIP_ROLE_INVALID")
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
        or members != set(command.portfolio_instrument_ids) | set(command.watchlist_instrument_ids)
        or {member.instrument_id for member in prepared.members} != members
    ):
        raise WeeklyError("WEEKLY_AUTHORIZATION_HASH_OR_RELATION_INVALID")
    blocker = (
        "WEEKLY_REVOKED"
        if pointer.revoked
        else "WEEKLY_PAUSED"
        if not pointer.enabled
        else "WEEKLY_AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID"
        if not command.valid_from <= now < command.valid_until
        else None
    )
    return WeeklyConfiguration(
        schedule_id=pointer.id,
        revision_id=record.id,
        version=pointer.version,
        enabled=pointer.enabled,
        revoked=pointer.revoked,
        prepared=prepared,
        blocker=blocker,
    )


def verify_report(record: WeeklyReportRecord, now: datetime) -> WeeklyReport:
    try:
        report = WeeklyReport.model_validate(record.report_json)
        report.verify()
    except ValueError:
        raise WeeklyError("WEEKLY_REPORT_SCHEMA_OR_HASH_INVALID") from None
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
        raise WeeklyError("WEEKLY_REPORT_RELATION_INVALID")
    if now >= report.usable_until:
        raise WeeklyError("WEEKLY_REPORT_EXPIRED_HISTORY_PRESERVED")
    return report


async def verify_relations(
    session: AsyncSession, record: WeeklyReportRecord, report: WeeklyReport
) -> None:
    authorization = await session.get(WeeklyAuthorizationRecord, record.revision_id)
    if (
        authorization is None
        or authorization.schedule_id != report.schedule_id
        or fingerprint(authorization.prepared_json)
        != fingerprint(report.authorization.model_dump(mode="json"))
        or authorization.content_hash != report.authorization.content_hash
    ):
        raise WeeklyError("WEEKLY_REPORT_AUTHORIZATION_REFERENCE_INVALID")
    evidence = set(
        await session.scalars(
            select(WeeklyReportEvidenceRecord.evidence_id).where(
                WeeklyReportEvidenceRecord.report_id == record.id
            )
        )
    )
    if evidence != set(report.evidence_diff.visible_ids if report.evidence_diff else ()):
        raise WeeklyError("WEEKLY_REPORT_EVIDENCE_REFERENCE_INVALID")
    rows = (
        await session.scalars(
            select(WeeklyReportReferenceRecord).where(
                WeeklyReportReferenceRecord.report_id == record.id
            )
        )
    ).all()
    actual = {(row.kind, row.record_id, row.instrument_id, row.content_hash) for row in rows}
    expected = {
        (ref.kind, ref.record_id, ref.instrument_id, ref.content_hash)
        for holding in report.holdings
        for ref in holding.references
    }
    if actual != expected:
        raise WeeklyError("WEEKLY_REPORT_HISTORICAL_REFERENCE_INVALID")


class SqlWeeklyReview:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def preview(self, command: WeeklySave, now: datetime) -> WeeklyPrepared:
        async with self.sessions() as session:
            prepared, _ = await capture(session, command, now, lock=False)
            return prepared

    async def _receipt(
        self, session: AsyncSession, identifier: UUID, payload: dict[str, Any]
    ) -> WeeklyConfiguration | None:
        record = await session.scalar(
            select(EventLogRecord).where(
                EventLogRecord.event_type == "weekly.command",
                EventLogRecord.aggregate_id == identifier,
            )
        )
        if record is None:
            return None
        if record.payload_json.get("command_hash") != fingerprint(payload):
            raise WeeklyError("WEEKLY_REQUEST_CONTENT_CONFLICT")
        try:
            return WeeklyConfiguration.model_validate(record.payload_json["result"])
        except (KeyError, ValueError):
            raise WeeklyError("WEEKLY_COMMAND_RECEIPT_INVALID") from None

    async def save(self, command: WeeklySave, preview_hash: str) -> WeeklyConfiguration:
        payload = {
            "kind": "SAVE",
            "command": command.model_dump(mode="json"),
            "preview_hash": preview_hash,
        }
        async with self.sessions() as session, session.begin():
            await lock(session, "weekly-command", command.request_id)
            prior = await self._receipt(session, command.request_id, payload)
            if prior:
                return prior
            await lock(session, "weekly-configuration", command.schedule_id)
            pointer = await session.get(
                WeeklyConfigurationRecord, command.schedule_id, with_for_update=True
            )
            if pointer and pointer.revoked:
                raise WeeklyError("WEEKLY_REVOKED")
            if (pointer.version if pointer else 0) != command.expected_version:
                raise WeeklyError("WEEKLY_VERSION_CONFLICT")
            prepared, _ = await capture(session, command, datetime.now(UTC), lock=True)
            if prepared.content_hash != preview_hash:
                raise WeeklyError("WEEKLY_PREVIEW_STALE_REFRESH_AND_CONFIRM")
            revision_id = uuid4()
            if pointer is None:
                pointer = WeeklyConfigurationRecord(
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
                WeeklyAuthorizationRecord(
                    id=revision_id,
                    version=pointer.version,
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
                    WeeklyMemberRecord(
                        revision_id=revision_id, instrument_id=member.instrument_id, membership=role
                    )
                    for member in prepared.members
                    for role, included in (
                        ("PORTFOLIO", member.in_portfolio),
                        ("WATCHLIST", member.in_watchlist),
                    )
                    if included
                ]
            )
            await session.flush()
            session.add_all(
                [
                    WeeklyCalendarDayRecord(revision_id=revision_id, business_date=day, state=state)
                    for day, state in command.calendar_days.items()
                ]
            )
            await session.flush()
            result = await configuration(session, pointer, datetime.now(UTC))
            await emit(
                session,
                "weekly.command",
                command.request_id,
                dict(command_hash=fingerprint(payload), result=result.model_dump(mode="json")),
                datetime.now(UTC),
            )
            return result

    async def mode(self, schedule_id: UUID, command: DailyMode) -> WeeklyConfiguration:
        payload = {
            "kind": "MODE",
            "schedule_id": str(schedule_id),
            **command.model_dump(mode="json"),
        }
        async with self.sessions() as session, session.begin():
            await lock(session, "weekly-command", command.request_id)
            prior = await self._receipt(session, command.request_id, payload)
            if prior:
                return prior
            await lock(session, "weekly-configuration", schedule_id)
            pointer = await session.get(
                WeeklyConfigurationRecord, schedule_id, with_for_update=True
            )
            if pointer is None:
                raise WeeklyError("WEEKLY_CONFIGURATION_NOT_FOUND")
            if pointer.revoked:
                raise WeeklyError("WEEKLY_REVOKED")
            if pointer.version != command.expected_version:
                raise WeeklyError("WEEKLY_VERSION_CONFLICT")
            current = await configuration(session, pointer, datetime.now(UTC))
            if command.action == "ENABLE":
                if current.prepared is None:
                    raise WeeklyError("WEEKLY_LEGACY_UNVERIFIED_CREATE_NEW_AUTHORIZATION")
                prepared, _ = await capture(
                    session, current.prepared.command, datetime.now(UTC), lock=True
                )
                if prepared.content_hash != current.prepared.content_hash:
                    raise WeeklyError("WEEKLY_SCOPE_OR_CALENDAR_CHANGED")
                # Recheck time after all awaited capture before the write.
                if (
                    not prepared.command.valid_from
                    <= datetime.now(UTC)
                    < prepared.command.valid_until
                ):
                    raise WeeklyError("WEEKLY_AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID")
            pointer.version += 1
            pointer.enabled = command.action == "ENABLE"
            pointer.revoked = command.action == "REVOKE"
            result = await configuration(session, pointer, datetime.now(UTC))
            await emit(
                session,
                "weekly.command",
                command.request_id,
                dict(command_hash=fingerprint(payload), result=result.model_dump(mode="json")),
                datetime.now(UTC),
            )
            return result

    async def configurations(self, offset: int = 0) -> tuple[WeeklyConfiguration, ...]:
        check_offset(offset)
        result = []
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(WeeklyConfigurationRecord)
                    .order_by(
                        WeeklyConfigurationRecord.created_at.desc(),
                        WeeklyConfigurationRecord.id.desc(),
                    )
                    .offset(offset)
                    .limit(50)
                )
            ).all()
            for pointer in rows:
                config = await configuration(session, pointer, datetime.now(UTC))
                if config.blocker is None and config.prepared is not None:
                    try:
                        prepared, _ = await capture(
                            session, config.prepared.command, datetime.now(UTC), lock=False
                        )
                        if prepared.content_hash != config.prepared.content_hash:
                            raise WeeklyError("WEEKLY_SCOPE_OR_CALENDAR_CHANGED")
                    except WeeklyError as exc:
                        config = config.model_copy(update={"blocker": exc.code})
                result.append(config)
        return tuple(result)

    async def reports(
        self, schedule_id: UUID | None = None, offset: int = 0
    ) -> tuple[WeeklyReport, ...]:
        check_offset(offset)
        statement = select(WeeklyReportRecord).where(
            WeeklyReportRecord.usable_until > datetime.now(UTC)
        )
        if schedule_id:
            statement = statement.where(WeeklyReportRecord.schedule_id == schedule_id)
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    statement.order_by(
                        WeeklyReportRecord.recorded_at.desc(), WeeklyReportRecord.id.desc()
                    )
                    .offset(offset)
                    .limit(60)
                )
            ).all()
            result = []
            for row in rows:
                report = verify_report(row, datetime.now(UTC))
                await verify_relations(session, row, report)
                result.append(report)
            return tuple(result)

    async def replay(self, report_id: UUID) -> WeeklyReport:
        async with self.sessions() as session:
            record = await session.get(WeeklyReportRecord, report_id)
            if record is None:
                raise WeeklyError("WEEKLY_REPORT_NOT_FOUND")
            report = verify_report(record, datetime.now(UTC))
            await verify_relations(session, record, report)
            return report

    async def history(self, offset: int = 0) -> tuple[WeeklyReportHistory, ...]:
        check_offset(offset)
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(WeeklyReportRecord)
                    .order_by(WeeklyReportRecord.recorded_at.desc(), WeeklyReportRecord.id.desc())
                    .offset(offset)
                    .limit(60)
                )
            ).all()
            return tuple(
                WeeklyReportHistory(
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

    async def runs(self, offset: int = 0) -> tuple[DailyTask, ...]:
        check_offset(offset)
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(TaskRunRecord)
                    .where(TaskRunRecord.task_name == "weekly_portfolio_review")
                    .order_by(TaskRunRecord.started_at.desc(), TaskRunRecord.id.desc())
                    .offset(offset)
                    .limit(60)
                )
            ).all()
            # TaskRun logical keys bind schedule/revision/week even on rolled-back failures.
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


def check_offset(offset: int) -> None:
    if type(offset) is not int or not 0 <= offset <= 1000000:
        raise WeeklyError("WEEKLY_PAGINATION_INVALID")
