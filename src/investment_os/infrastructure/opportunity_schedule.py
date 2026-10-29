"""Transactional zero-egress weekly local funnel configuration and execution."""

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.calendar_product import CalendarSessionInput, calendar_hash
from investment_os.application.opportunities import (
    FunnelQuery,
    OpportunityError,
    OpportunityService,
)
from investment_os.application.opportunity_schedule import (
    WeeklyConfiguration,
    WeeklyMode,
    WeeklyOverview,
    WeeklyResult,
    WeeklySave,
    covered_weeks,
    week_due,
)
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.application.schedule import MarketVenue
from investment_os.infrastructure.opportunities import SqlOpportunityStore
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
    InstrumentRecord,
    OutboxEventRecord,
    TaskRunRecord,
)
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork
from investment_os.infrastructure.weekly_funnel_models import (
    WeeklyConfigurationRecord,
    WeeklyMemberRecord,
    WeeklyResultRecord,
    WeeklyRevisionRecord,
)

_COMMAND = "weekly_funnel_command"


def audit(identifier: UUID) -> dict[str, object]:
    return {
        "created_by": "weekly_local_funnel",
        "correlation_id": identifier,
        "schema_version": "1.0",
        "metadata_json": {},
    }


async def emit(
    session: AsyncSession, kind: str, identifier: UUID, payload: dict[str, object]
) -> None:
    event = EventLogRecord(
        id=uuid4(),
        event_type=kind,
        aggregate_type=_COMMAND,
        aggregate_id=identifier,
        occurred_at=datetime.now(UTC),
        payload_json=payload,
        **audit(identifier),
    )
    session.add(event)
    await session.flush()
    session.add(
        AuditLogRecord(
            actor_type="HUMAN" if kind.endswith("command") else "SYSTEM",
            actor_id="local-owner" if kind.endswith("command") else "weekly_local_funnel",
            operation=kind,
            entity_type="WeeklyLocalFunnel",
            entity_id=identifier,
            before_hash=None,
            after_hash=fingerprint(payload),
            ip_or_runtime_ref="weekly_local_funnel",
            occurred_at=datetime.now(UTC),
            **audit(identifier),
        )
    )
    session.add(
        OutboxEventRecord(
            event_id=event.id,
            topic=kind,
            payload_json={"id": str(identifier), "content_hash": fingerprint(payload)},
            **audit(identifier),
        )
    )


async def calendar(
    session: AsyncSession, identifier: UUID, venue: str, *, lock: bool = False
) -> tuple[CalendarImportRecord, Sequence[MarketSessionRecord]]:
    config = await session.scalar(
        select(CalendarConfigurationRecord)
        .where(CalendarConfigurationRecord.venue == venue)
        .with_for_update()
        if lock
        else select(CalendarConfigurationRecord).where(CalendarConfigurationRecord.venue == venue)
    )
    if config is None or config.active_import_id != identifier:
        raise OpportunityError("WEEKLY_CALENDAR_CHANGED_OR_MISSING")
    source = await session.get(CalendarImportRecord, identifier)
    days = (
        await session.scalars(
            select(MarketSessionRecord)
            .where(MarketSessionRecord.import_id == identifier)
            .order_by(MarketSessionRecord.business_date)
        )
    ).all()
    if source is None or source.venue != venue or not days:
        raise OpportunityError("WEEKLY_CALENDAR_INVALID")
    snapshots = tuple(
        CalendarSessionInput(business_date=d.business_date, close_at_utc=d.close_at_utc)
        for d in days
    )
    if (
        calendar_hash(MarketVenue(venue), source.source_name, source.source_version, snapshots)
        != source.content_hash
    ):
        raise OpportunityError("WEEKLY_CALENDAR_INVALID")
    return source, days


def revision_payload(revision: WeeklyRevisionRecord) -> dict[str, object]:
    return {
        "name": revision.name,
        "venue": revision.venue,
        "calendar_import_id": str(revision.calendar_import_id),
        "calendar_hash": revision.calendar_hash,
        "coverage_start": revision.coverage_start.isoformat(),
        "coverage_end": revision.coverage_end.isoformat(),
        "template_run_id": str(revision.template_run_id),
        "template": revision.template_json,
    }


async def read_revision(
    session: AsyncSession, config: WeeklyConfigurationRecord
) -> WeeklyRevisionRecord:
    revision = await session.get(WeeklyRevisionRecord, config.revision_id)
    if (
        revision is None
        or revision.schedule_id != config.id
        or fingerprint(revision_payload(revision)) != revision.content_hash
    ):
        raise OpportunityError("WEEKLY_SNAPSHOT_INVALID")
    template = FunnelQuery.model_validate(revision.template_json)
    members = set(
        (
            await session.scalars(
                select(WeeklyMemberRecord.instrument_id).where(
                    WeeklyMemberRecord.revision_id == revision.id
                )
            )
        ).all()
    )
    if members != set(template.instrument_ids):
        raise OpportunityError("WEEKLY_SCOPE_INVALID")
    return revision


async def view(session: AsyncSession, config: WeeklyConfigurationRecord) -> WeeklyConfiguration:
    revision = await read_revision(session, config)
    source = await session.get(CalendarImportRecord, revision.calendar_import_id)
    blocker = None
    try:
        await calendar(session, revision.calendar_import_id, revision.venue)
    except OpportunityError as exc:
        blocker = exc.code
    if not config.enabled:
        blocker = "WEEKLY_PAUSED"
    return WeeklyConfiguration(
        schedule_id=config.id,
        revision_id=revision.id,
        version=config.version,
        name=revision.name,
        venue=revision.venue,
        enabled=config.enabled,
        calendar_import_id=revision.calendar_import_id,
        calendar_source=source.source_name if source else "",
        calendar_version=source.source_version if source else "",
        calendar_hash=revision.calendar_hash,
        template_run_id=revision.template_run_id,
        coverage_start=revision.coverage_start,
        coverage_end=revision.coverage_end,
        template=FunnelQuery.model_validate(revision.template_json),
        blocker=blocker,
    )


class SqlWeeklyFunnel:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions
        self.funnels = SqlOpportunityStore(sessions)

    async def _receipt(
        self, session: AsyncSession, request_id: UUID, digest: str
    ) -> WeeklyConfiguration | None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": advisory_lock_key(_COMMAND, str(request_id))},
        )
        prior = await session.scalar(
            select(EventLogRecord).where(
                EventLogRecord.aggregate_type == _COMMAND,
                EventLogRecord.aggregate_id == request_id,
                EventLogRecord.event_type == "weekly.command",
            )
        )
        if prior:
            if prior.payload_json["request_hash"] != digest:
                raise OpportunityError("REQUEST_CONTENT_CONFLICT")
            return WeeklyConfiguration.model_validate(prior.payload_json["result"])
        return None

    async def save(self, command: WeeklySave) -> WeeklyConfiguration:
        digest = fingerprint(command.model_dump(mode="json"))
        # Template is immutable; no service performs external calls.
        funnel = await self.funnels.get_run(command.funnel_run_id)
        if funnel is None:
            raise OpportunityError("FUNNEL_RUN_NOT_FOUND")
        async with self.sessions() as session, session.begin():
            replay = await self._receipt(session, command.request_id, digest)
            if replay:
                return replay
            # Serialize the global capacity check, including concurrent creates with distinct IDs.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": advisory_lock_key("weekly-config-capacity", "all")},
            )
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": advisory_lock_key("weekly-config", str(command.schedule_id))},
            )
            config = await session.get(
                WeeklyConfigurationRecord, command.schedule_id, with_for_update=True
            )
            if (
                config is None
                and (
                    await session.scalar(
                        select(func.count()).select_from(WeeklyConfigurationRecord)
                    )
                    or 0
                )
                >= 50
            ):
                raise OpportunityError("WEEKLY_CONFIGURATION_LIMIT")
            if (config.version if config else 0) != command.expected_version:
                raise OpportunityError("WEEKLY_VERSION_CONFLICT")
            source, _ = await calendar(
                session, command.calendar_import_id, command.venue, lock=True
            )
            instruments = (
                await session.scalars(
                    select(InstrumentRecord).where(
                        InstrumentRecord.id.in_(funnel.query.instrument_ids)
                    )
                )
            ).all()
            if (
                not instruments
                or len(instruments) != len(funnel.query.instrument_ids)
                or any(
                    row.exchange != command.venue or row.currency != "CNY" for row in instruments
                )
            ):
                raise OpportunityError("WEEKLY_SCOPE_MARKET_MISMATCH")
            revision_id = uuid4()
            if config is None:
                config = WeeklyConfigurationRecord(
                    id=command.schedule_id,
                    revision_id=revision_id,
                    version=1,
                    enabled=False,
                    **audit(command.request_id),
                )
                session.add(config)
            else:
                config.revision_id, config.version, config.enabled = (
                    revision_id,
                    config.version + 1,
                    False,
                )
            await session.flush()  # The revision pointer FK is deferred until commit.
            revision = WeeklyRevisionRecord(
                id=revision_id,
                schedule_id=config.id,
                name=command.name,
                venue=command.venue,
                calendar_import_id=source.id,
                calendar_hash=source.content_hash,
                coverage_start=command.coverage_start,
                coverage_end=command.coverage_end,
                template_run_id=funnel.run_id,
                template_json=funnel.query.model_dump(mode="json"),
                content_hash="",
                **audit(command.request_id),
            )
            revision.content_hash = fingerprint(revision_payload(revision))
            session.add(revision)
            await session.flush()
            session.add_all(
                [
                    WeeklyMemberRecord(revision_id=revision_id, instrument_id=i)
                    for i in funnel.query.instrument_ids
                ]
            )
            await session.flush()
            result = await view(session, config)
            await emit(
                session,
                "weekly.command",
                command.request_id,
                {
                    "request_hash": digest,
                    "command": command.model_dump(mode="json"),
                    "result": result.model_dump(mode="json"),
                },
            )
            return result

    async def mode(self, schedule_id: UUID, command: WeeklyMode) -> WeeklyConfiguration:
        digest = fingerprint({"schedule_id": str(schedule_id), **command.model_dump(mode="json")})
        async with self.sessions() as session, session.begin():
            replay = await self._receipt(session, command.request_id, digest)
            if replay:
                return replay
            config = await session.get(WeeklyConfigurationRecord, schedule_id, with_for_update=True)
            if config is None or config.version != command.expected_version:
                raise OpportunityError("WEEKLY_VERSION_CONFLICT")
            revision = await read_revision(session, config)
            if command.enabled:
                await calendar(session, revision.calendar_import_id, revision.venue, lock=True)
            if config.enabled != command.enabled:
                config.enabled, config.version = command.enabled, config.version + 1
            result = await view(session, config)
            await emit(
                session,
                "weekly.command",
                command.request_id,
                {
                    "request_hash": digest,
                    "command": command.model_dump(mode="json"),
                    "result": result.model_dump(mode="json"),
                },
            )
            return result

    async def overview(self) -> WeeklyOverview:
        async with self.sessions() as session:
            configs = (
                await session.scalars(
                    select(WeeklyConfigurationRecord)
                    .order_by(WeeklyConfigurationRecord.created_at.desc())
                    .limit(50)
                )
            ).all()
            configurations = tuple([await view(session, config) for config in configs])
            tasks = (
                await session.scalars(
                    select(TaskRunRecord)
                    .where(TaskRunRecord.task_name.like("weekly-local:%"))
                    .order_by(TaskRunRecord.started_at.desc())
                    .limit(50)
                )
            ).all()
            runs = []
            for task in tasks:
                result = await session.scalar(
                    select(WeeklyResultRecord).where(WeeklyResultRecord.task_run_id == task.id)
                )
                parts = task.idempotency_key.split(":")
                runs.append(
                    WeeklyResult(
                        task_run_id=task.id,
                        schedule_id=UUID(task.task_name.split(":")[-1]),
                        revision_id=UUID(parts[-2]),
                        week_start=date.fromisoformat(parts[-1]),
                        scheduled_for=task.scheduled_for,
                        as_of=result.as_of if result else None,
                        status=result.status if result else task.status,
                        reason_code=result.reason_code
                        if result
                        else (task.error_json or {}).get("type"),
                        attempt=task.attempt,
                        funnel_run_id=result.funnel_run_id if result else None,
                        candidate_count=result.candidate_count if result else None,
                    )
                )
            return WeeklyOverview(configurations=configurations, recent_runs=tuple(runs))


class WeeklyConfigurationChanged(RuntimeError):
    pass


class WeeklyFunnelRunner:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], service: OpportunityService):
        self.sessions, self.service = sessions, service
        self.funnels = SqlOpportunityStore(sessions)

    async def dispatch_due(self, *, now: datetime) -> tuple[UUID, ...]:
        if now.utcoffset() is None:
            raise ValueError("weekly clock must be timezone-aware")
        planned = []
        async with self.sessions() as session:
            configs = (
                await session.scalars(
                    select(WeeklyConfigurationRecord)
                    .where(WeeklyConfigurationRecord.enabled.is_(True))
                    .order_by(WeeklyConfigurationRecord.id)
                    .limit(50)
                )
            ).all()
            for config in configs:
                revision = await read_revision(session, config)
                try:
                    await calendar(session, revision.calendar_import_id, revision.venue)
                except OpportunityError:
                    continue  # Explicit blocker remains visible in overview; no guessed sessions.
                for week in covered_weeks(revision.coverage_start, revision.coverage_end):
                    if week_due(week) > now:
                        continue
                    key = f"weekly-funnel:{revision.id}:{week}"
                    prior = await session.scalar(
                        select(TaskRunRecord).where(TaskRunRecord.idempotency_key == key)
                    )
                    if prior and (prior.status == "SUCCEEDED" or prior.attempt >= 3):
                        continue
                    planned.append(
                        (config.id, config.version, revision.id, week, key, revision.content_hash)
                    )
                    if len(planned) >= 8:
                        break
                if len(planned) >= 8:
                    break
        completed = []
        for schedule_id, version, revision_id, week, key, content_hash in planned[:8]:

            async def handler(
                uow: SqlAlchemyUnitOfWork,
                schedule_id: UUID = schedule_id,
                version: int = version,
                revision_id: UUID = revision_id,
                week: date = week,
                key: str = key,
            ) -> None:
                config = await uow.session.get(
                    WeeklyConfigurationRecord, schedule_id, with_for_update=True
                )
                if (
                    config is None
                    or not config.enabled
                    or config.version != version
                    or config.revision_id != revision_id
                ):
                    raise WeeklyConfigurationChanged("weekly configuration was paused or replaced")
                revision = await read_revision(uow.session, config)
                source, days = await calendar(
                    uow.session, revision.calendar_import_id, revision.venue, lock=True
                )
                if source.content_hash != revision.calendar_hash:
                    raise WeeklyConfigurationChanged("weekly calendar changed")
                sessions = [d for d in days if week <= d.business_date < week + timedelta(days=7)]
                query = FunnelQuery.model_validate(revision.template_json).model_copy(
                    update={
                        "request_id": uuid5(revision.id, str(week)),
                        "as_of": max(d.close_at_utc for d in sessions)
                        if sessions
                        else week_due(week).astimezone(UTC),
                    }
                )
                funnel = await self.service.prepare_run(query) if sessions else None
                event_id = None
                if funnel:
                    await self.funnels.save_run_in(uow, funnel)
                    event_id = await uow.session.scalar(
                        select(EventLogRecord.id).where(
                            EventLogRecord.aggregate_type == "opportunity_funnel_run",
                            EventLogRecord.aggregate_id == funnel.run_id,
                        )
                    )
                task = await uow.task_runs.get_by_idempotency_key(key)
                if task is None:
                    raise RuntimeError("weekly TaskRun unavailable")
                result_id = uuid4()
                result = WeeklyResultRecord(
                    id=result_id,
                    task_run_id=task.id,
                    revision_id=revision.id,
                    week_start=week,
                    as_of=query.as_of,
                    status=funnel.status if funnel else "SKIPPED_CLOSED",
                    reason_code="LOCAL_DATA_MISSING"
                    if funnel and funnel.status == "DEGRADED"
                    else "MARKET_CLOSED"
                    if not funnel
                    else None,
                    funnel_run_id=funnel.run_id if funnel else None,
                    funnel_event_id=event_id,
                    candidate_count=len(funnel.candidate_ids) if funnel else None,
                    **audit(task.correlation_id),
                )
                uow.session.add(result)
                await emit(
                    uow.session,
                    "weekly.completed",
                    result_id,
                    {
                        "schedule_id": str(schedule_id),
                        "week_start": str(week),
                        "status": result.status,
                        "funnel_run_id": str(funnel.run_id) if funnel else None,
                        "external_calls": 0,
                        "model_calls": 0,
                        "paid_calls": 0,
                        "auto_trade": False,
                    },
                )

            try:
                result = await ReliableJobExecutor(self.sessions).execute(
                    task_name=f"weekly-local:{schedule_id}",
                    scheduled_for=week_due(week),
                    idempotency_key=key,
                    input_hash=fingerprint(
                        {"revision": str(revision_id), "hash": content_hash, "week": str(week)}
                    ),
                    handler=handler,
                )
                completed.append(result.task_run_id)
            except Exception:
                # Durable failed TaskRun is visible; bounded retries on later ticks, no paid work.
                continue
        return tuple(completed)
