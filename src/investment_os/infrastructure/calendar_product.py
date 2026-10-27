"""Atomic calendar configuration commands and durable, unpaid Worker status dispatch."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.calendar_product import (
    CalendarConfigurationView,
    CalendarImportCommand,
    CalendarModeCommand,
    CalendarOverview,
    CalendarPreview,
    CalendarProductError,
    CalendarRunView,
    CalendarSessionInput,
    CalendarStatusReport,
    calendar_hash,
)
from investment_os.application.errors import ApplicationError
from investment_os.application.schedule import MarketVenue
from investment_os.infrastructure.persistence.calendar_models import (
    CalendarConfigurationRecord,
    CalendarImportRecord,
    MarketSessionRecord,
)
from investment_os.infrastructure.persistence.jobs import ReliableJobExecutor
from investment_os.infrastructure.persistence.locks import advisory_lock_key
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    EventLogRecord,
    OutboxEventRecord,
    TaskRunRecord,
)
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork

COMMAND_EVENT = "calendar.command.saved"
REPORT_EVENT = "calendar.status.report"


def _hash(payload: object) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


async def _lock(session: AsyncSession, namespace: str, key: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": advisory_lock_key(namespace, key)}
    )


async def _preview(session: AsyncSession, record: CalendarImportRecord) -> CalendarPreview:
    rows = (
        await session.scalars(
            select(MarketSessionRecord)
            .where(MarketSessionRecord.import_id == record.id)
            .order_by(MarketSessionRecord.business_date)
        )
    ).all()
    venue = MarketVenue(record.venue)
    values = tuple(
        CalendarSessionInput(
            business_date=row.business_date, close_at_utc=row.close_at_utc.astimezone(UTC)
        )
        for row in rows
    )
    if (
        not 1 <= len(values) <= 1000
        or any(v.close_at_utc.astimezone(venue.timezone).date() != v.business_date for v in values)
        or calendar_hash(venue, record.source_name, record.source_version, values)
        != record.content_hash
    ):
        raise CalendarProductError(
            "CALENDAR_STORED_INVALID",
            "已保存日历无法核对, 已停止使用。请核对来源后重新导入。",
            conflict=True,
        )
    return CalendarPreview(
        venue=venue,
        market_timezone=venue.timezone.key,
        source_name=record.source_name,
        source_version=record.source_version,
        content_hash=record.content_hash,
        sessions=values,
    )


async def _view(
    session: AsyncSession, config: CalendarConfigurationRecord, *, now: datetime
) -> CalendarConfigurationView:
    record = await session.get(CalendarImportRecord, config.active_import_id)
    if record is None or record.venue != config.venue:
        raise CalendarProductError(
            "CALENDAR_STORED_INVALID", "日历配置来源不匹配, 已停止使用。", conflict=True
        )
    preview = await _preview(session, record)
    future = [s.close_at_utc for s in preview.sessions if s.close_at_utc > now]
    return CalendarConfigurationView(
        venue=preview.venue,
        market_timezone=preview.market_timezone,
        version=config.version,
        import_id=record.id,
        enabled=config.enabled,
        source_name=record.source_name,
        source_version=record.source_version,
        content_hash=record.content_hash,
        imported_at=record.imported_at,
        session_count=len(preview.sessions),
        first_business_date=preview.sessions[0].business_date,
        last_business_date=preview.sessions[-1].business_date,
        next_close_at=min(future) if future else None,
    )


def _append_event(
    uow: SqlAlchemyUnitOfWork,
    *,
    event_type: str,
    aggregate_id: UUID,
    payload: dict[str, object],
    now: datetime,
    request_id: UUID,
    before_hash: str | None = None,
) -> None:
    event = EventLogRecord(
        event_type=event_type,
        aggregate_type="calendar_product",
        aggregate_id=aggregate_id,
        payload_json=payload,
        occurred_at=now,
        correlation_id=request_id,
        created_by="calendar_product",
        schema_version="1.0",
        metadata_json={},
    )
    uow.session.add(event)
    event.id = uuid4()
    uow.session.add(
        OutboxEventRecord(
            event_id=event.id,
            topic=event_type,
            payload_json={"event_id": str(event.id), "content_hash": _hash(payload)},
            attempts=0,
            created_by="calendar_product",
            correlation_id=request_id,
            causation_id=event.id,
            schema_version="1.0",
            metadata_json={},
        )
    )
    uow.session.add(
        AuditLogRecord(
            actor_type="SYSTEM" if event_type == REPORT_EVENT else "HUMAN",
            actor_id="calendar_product",
            operation=event_type,
            entity_type="calendar_product",
            entity_id=aggregate_id,
            before_hash=before_hash,
            after_hash=_hash(payload),
            ip_or_runtime_ref="worker" if event_type == REPORT_EVENT else "local_api",
            occurred_at=now,
            correlation_id=request_id,
            schema_version="1.0",
            created_by="calendar_product",
            metadata_json={},
        )
    )


class SqlCalendarProduct:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def overview(self) -> CalendarOverview:
        now = datetime.now(UTC)
        async with self.sessions() as session:
            configs = (
                await session.scalars(
                    select(CalendarConfigurationRecord).order_by(CalendarConfigurationRecord.venue)
                )
            ).all()
            views = tuple([await _view(session, c, now=now) for c in configs])
            runs = (
                await session.scalars(
                    select(TaskRunRecord)
                    .where(TaskRunRecord.task_name.startswith("calendar_status_", autoescape=True))
                    .order_by(TaskRunRecord.started_at.desc())
                    .limit(30)
                )
            ).all()
            reports = (
                (
                    await session.scalars(
                        select(EventLogRecord).where(
                            EventLogRecord.event_type == REPORT_EVENT,
                            EventLogRecord.aggregate_id.in_([r.id for r in runs]),
                        )
                    )
                ).all()
                if runs
                else []
            )
            by_id = {r.aggregate_id: r.payload_json for r in reports}
            if any(r.status == "SUCCEEDED" and r.id not in by_id for r in runs):
                raise CalendarProductError(
                    "CALENDAR_REPORT_UNAVAILABLE",
                    "运行记录缺少可核对的状态报告, 未伪造成功。请检查服务数据。",
                    conflict=True,
                )
            return CalendarOverview(
                configurations=views,
                recent_runs=tuple(
                    CalendarRunView(
                        task_run_id=r.id,
                        task_name=r.task_name,
                        as_of=r.scheduled_for,
                        status=r.status,
                        attempt=r.attempt,
                        started_at=r.started_at,
                        finished_at=r.finished_at,
                        error_code=r.error_json.get("code") if r.error_json else None,
                        report=CalendarStatusReport.model_validate(by_id[r.id])
                        if r.id in by_id
                        else None,
                    )
                    for r in runs
                ),
            )

    async def _replay(
        self, uow: SqlAlchemyUnitOfWork, request_id: UUID, fingerprint: str
    ) -> CalendarConfigurationView | None:
        await _lock(uow.session, "calendar-request", str(request_id))
        event = await uow.session.scalar(
            select(EventLogRecord).where(
                EventLogRecord.event_type == COMMAND_EVENT,
                EventLogRecord.aggregate_id == request_id,
            )
        )
        if event is None:
            return None
        if event.payload_json["request_hash"] != fingerprint:
            raise CalendarProductError(
                "CALENDAR_REQUEST_CONFLICT",
                "请求标识已用于其他内容。当前输入未保存, 请重新核对。",
                conflict=True,
            )
        return CalendarConfigurationView.model_validate(event.payload_json["result"])

    async def import_calendar(
        self, command: CalendarImportCommand, preview: CalendarPreview
    ) -> CalendarConfigurationView:
        fingerprint = _hash(
            {"kind": "import", "command": command.model_dump(mode="json", exclude={"request_id"})}
        )
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            replay = await self._replay(uow, command.request_id, fingerprint)
            if replay is not None:
                return replay
            await _lock(uow.session, "calendar-venue", command.venue.value)
            config = await uow.session.scalar(
                select(CalendarConfigurationRecord)
                .where(CalendarConfigurationRecord.venue == command.venue.value)
                .with_for_update()
            )
            if (config.version if config else 0) != command.expected_version:
                raise CalendarProductError(
                    "CALENDAR_VERSION_CONFLICT",
                    "日历已被其他操作更新。本次未覆盖, 请保留草稿并刷新核对。",
                    conflict=True,
                )
            now, before_hash = datetime.now(UTC), None
            if config:
                before_hash = _hash(
                    (await _view(uow.session, config, now=now)).model_dump(mode="json")
                )
            old = (
                await uow.session.get(CalendarImportRecord, config.active_import_id)
                if config
                else None
            )
            if old is None or old.content_hash != preview.content_hash:
                record = CalendarImportRecord(
                    id=uuid4(),
                    venue=command.venue.value,
                    source_name=preview.source_name,
                    source_version=preview.source_version,
                    content_hash=preview.content_hash,
                    imported_at=now,
                    created_by="human_calendar_import",
                    correlation_id=command.request_id,
                    metadata_json={"confirmed_source": True, "scope": "STATUS_ONLY"},
                )
                uow.session.add(record)
                await uow.session.flush()
                uow.session.add_all(
                    MarketSessionRecord(
                        import_id=record.id,
                        business_date=s.business_date,
                        close_at_utc=s.close_at_utc,
                        created_by="human_calendar_import",
                        correlation_id=command.request_id,
                        metadata_json={},
                    )
                    for s in preview.sessions
                )
                if config is None:
                    config = CalendarConfigurationRecord(
                        venue=command.venue.value,
                        active_import_id=record.id,
                        enabled=False,
                        version=1,
                        created_by="human_calendar_import",
                        correlation_id=command.request_id,
                        metadata_json={},
                    )
                    uow.session.add(config)
                else:
                    config.active_import_id, config.enabled, config.version = (
                        record.id,
                        False,
                        config.version + 1,
                    )
            await uow.session.flush()
            assert config is not None
            result = await _view(uow.session, config, now=now)
            _append_event(
                uow,
                event_type=COMMAND_EVENT,
                aggregate_id=command.request_id,
                payload={
                    "kind": "import",
                    "request_hash": fingerprint,
                    "result": result.model_dump(mode="json"),
                },
                now=now,
                request_id=command.request_id,
                before_hash=before_hash,
            )
            await uow.commit()
            return result

    async def set_mode(
        self, venue: MarketVenue, command: CalendarModeCommand
    ) -> CalendarConfigurationView:
        fingerprint = _hash(
            {
                "kind": "mode",
                "venue": venue.value,
                "command": command.model_dump(mode="json", exclude={"request_id"}),
            }
        )
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            replay = await self._replay(uow, command.request_id, fingerprint)
            if replay is not None:
                return replay
            await _lock(uow.session, "calendar-venue", venue.value)
            config = await uow.session.scalar(
                select(CalendarConfigurationRecord)
                .where(CalendarConfigurationRecord.venue == venue.value)
                .with_for_update()
            )
            if config is None or config.version != command.expected_version:
                raise CalendarProductError(
                    "CALENDAR_VERSION_CONFLICT",
                    "日历配置不存在或已更新。本次未改变启用状态, 请刷新核对。",
                    conflict=True,
                )
            now = datetime.now(UTC)
            before_hash = _hash((await _view(uow.session, config, now=now)).model_dump(mode="json"))
            if config.enabled != command.enabled:
                config.enabled, config.version = command.enabled, config.version + 1
            await uow.session.flush()
            result = await _view(uow.session, config, now=now)
            _append_event(
                uow,
                event_type=COMMAND_EVENT,
                aggregate_id=command.request_id,
                payload={
                    "kind": "mode",
                    "request_hash": fingerprint,
                    "result": result.model_dump(mode="json"),
                },
                now=now,
                request_id=command.request_id,
                before_hash=before_hash,
            )
            await uow.commit()
            return result


class CalendarConfigurationChanged(RuntimeError):
    """The active configuration changed after planning; no report was generated."""


class PersistedCalendarStatusRunner:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], *, max_replay_sessions: int = 1):
        if not 1 <= max_replay_sessions <= 31:
            raise ValueError("calendar batch must be between one and thirty-one sessions")
        self.sessions, self.maximum = sessions, max_replay_sessions

    async def dispatch_due(self, *, now: datetime) -> tuple[UUID, ...]:
        if now.utcoffset() is None:
            raise ValueError("calendar runtime now must be timezone-aware")
        now = now.astimezone(UTC)
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(MarketSessionRecord, CalendarImportRecord, CalendarConfigurationRecord)
                    .join(
                        CalendarImportRecord,
                        MarketSessionRecord.import_id == CalendarImportRecord.id,
                    )
                    .join(
                        CalendarConfigurationRecord,
                        CalendarConfigurationRecord.active_import_id == CalendarImportRecord.id,
                    )
                    .where(
                        CalendarConfigurationRecord.enabled.is_(True),
                        MarketSessionRecord.close_at_utc <= now,
                    )
                    .order_by(MarketSessionRecord.close_at_utc, MarketSessionRecord.id)
                )
            ).all()
            keys = [
                f"calendar-status:{config.venue}:{day.business_date}" for day, _, config in rows
            ]
            old = (
                (
                    await session.scalars(
                        select(TaskRunRecord).where(TaskRunRecord.idempotency_key.in_(keys))
                    )
                ).all()
                if keys
                else []
            )
            previous = {r.idempotency_key: r for r in old}
            # Validate each active imported payload before dispatch, not from the browser's preview.
            for record in {record.id: record for _, record, _ in rows}.values():
                await _preview(session, record)
            pending = [
                (day, record, config, key)
                for (day, record, config), key in zip(rows, keys, strict=True)
                if key not in previous
                or (previous[key].status != "SUCCEEDED" and previous[key].attempt < 3)
            ][: self.maximum]
        completed = []
        for day, record, config, key in pending:
            fingerprint = _hash(
                {
                    "venue": config.venue,
                    "business_date": day.business_date,
                    "close_at": day.close_at_utc,
                    "calendar_hash": record.content_hash,
                }
            )

            async def handler(
                uow: SqlAlchemyUnitOfWork,
                day: MarketSessionRecord = day,
                record: CalendarImportRecord = record,
                config: CalendarConfigurationRecord = config,
                key: str = key,
            ) -> None:
                active = await uow.session.scalar(
                    select(CalendarConfigurationRecord)
                    .where(CalendarConfigurationRecord.id == config.id)
                    .with_for_update()
                )
                if (
                    active is None
                    or not active.enabled
                    or active.active_import_id != record.id
                    or active.version != config.version
                ):
                    raise CalendarConfigurationChanged("calendar changed before status report")
                task = await uow.task_runs.get_by_idempotency_key(key)
                assert task is not None
                _append_event(
                    uow,
                    event_type=REPORT_EVENT,
                    aggregate_id=task.id,
                    payload={
                        "venue": config.venue,
                        "business_date": str(day.business_date),
                        "as_of": day.close_at_utc.isoformat(),
                        "calendar_import_id": str(record.id),
                        "calendar_hash": record.content_hash,
                        "source_name": record.source_name,
                        "source_version": record.source_version,
                        "report_kind": "CALENDAR_STATUS_ONLY",
                        "message": "日历状态报告已完成。团队研究、分析、决策、周月复核尚未接通, "
                        "本任务未调用模型或数据源。",
                        "auto_trade": False,
                        "paid_calls": 0,
                    },
                    now=now,
                    request_id=uuid4(),
                )

            try:
                result = await ReliableJobExecutor(self.sessions).execute(
                    task_name=f"calendar_status_{config.venue}",
                    scheduled_for=day.close_at_utc,
                    idempotency_key=key,
                    input_hash=fingerprint,
                    handler=handler,
                )
                completed.append(result.task_run_id)
            except (ApplicationError, CalendarConfigurationChanged):
                # Contention, bounded retries or a pause/import race never creates a fake report.
                continue
        return tuple(completed)
