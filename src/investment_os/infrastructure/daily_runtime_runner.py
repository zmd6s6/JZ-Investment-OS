"""Bounded daily dispatch: local transaction first, one explicit persistent research intent."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.analysis_configuration import AnalysisStartService
from investment_os.application.analysis_runs import AnalysisStart, analysis_command_payload
from investment_os.application.calendar_product import CalendarSessionInput
from investment_os.application.daily_report import build_daily_report
from investment_os.application.daily_runtime import (
    DailyConfiguration,
    DailyError,
    DailyReport,
    assert_authorized,
    evidence_diff,
)
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.application.runtime_authorization import RuntimeAuthorizationRef
from investment_os.application.schedule import MarketVenue
from investment_os.infrastructure.analysis_runs import SqlAnalysisRuns
from investment_os.infrastructure.daily_runtime_local import SqlDailyLocalReader
from investment_os.infrastructure.daily_runtime_models import (
    DailyAnalysisBindingRecord,
    DailyAnalysisIntentRecord,
    DailyConfigurationRecord,
    DailyExecutionRecord,
    DailyReportAnalysisRecord,
    DailyReportEvidenceRecord,
    DailyReportRecord,
)
from investment_os.infrastructure.daily_runtime_setup import capture_calendar
from investment_os.infrastructure.daily_runtime_store import common, configuration, emit
from investment_os.infrastructure.persistence.jobs import ReliableJobExecutor
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork


class DailyRuntimeRunner:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        local: SqlDailyLocalReader,
        starter: AnalysisStartService,
        analyses: SqlAnalysisRuns,
    ):
        self.sessions, self.local, self.starter, self.analyses = sessions, local, starter, analyses

    async def dispatch_due(self, *, now: datetime) -> tuple[UUID, ...]:
        if now.utcoffset() is None:
            raise DailyError("DAILY_CLOCK_TIMEZONE_REQUIRED")
        plans = []
        async with self.sessions() as session:
            pointers = (
                await session.scalars(
                    select(DailyConfigurationRecord)
                    .where(
                        DailyConfigurationRecord.enabled.is_(True),
                        DailyConfigurationRecord.revoked.is_(False),
                    )
                    .order_by(DailyConfigurationRecord.id)
                    .limit(50)
                )
            ).all()
            for pointer in pointers:
                config = await configuration(session, pointer)
                if config.blocker:
                    continue
                try:
                    _, days = await capture_calendar(session, config.prepared.command)
                except DailyError:
                    continue  # Configuration remains inspectable; no invented session.
                command = config.prepared.command
                for day in days:
                    if (
                        not command.coverage_start <= day.business_date <= command.coverage_end
                        or day.close_at_utc > now
                        or config.enabled_since is None
                        or day.close_at_utc < config.enabled_since
                    ):
                        continue
                    existing = await session.scalar(
                        select(DailyExecutionRecord.id).where(
                            DailyExecutionRecord.schedule_id == pointer.id,
                            DailyExecutionRecord.business_date == day.business_date,
                        )
                    )
                    if existing is None:
                        plans.append((config, day))
                    if len(plans) >= 8:
                        break
                if len(plans) >= 8:
                    break
        completed = []
        for config, day in plans:
            key = f"daily:{config.schedule_id}:{day.business_date}"

            async def handler(
                uow: SqlAlchemyUnitOfWork,
                config: DailyConfiguration = config,
                day: CalendarSessionInput = day,
                key: str = key,
            ) -> None:
                pointer = await uow.session.get(
                    DailyConfigurationRecord, config.schedule_id, with_for_update=True
                )
                if pointer is None:
                    raise DailyError("DAILY_CONFIGURATION_NOT_FOUND")
                current = await configuration(uow.session, pointer)
                assert_authorized(current, version=config.version, now=now)
                _, sessions = await capture_calendar(
                    uow.session, current.prepared.command, lock=True
                )
                if day not in sessions:
                    raise DailyError("DAILY_CALENDAR_CHANGED_OR_MISSING")
                local = await self.local.read(uow.session, current.prepared, now)
                task = await uow.task_runs.get_by_idempotency_key(key)
                if task is None:
                    raise DailyError("DAILY_TASK_REFERENCE_MISSING")
                execution_id, report_id = uuid4(), uuid4()
                prior = await uow.session.scalar(
                    select(DailyReportRecord)
                    .join(
                        DailyExecutionRecord,
                        DailyReportRecord.execution_id == DailyExecutionRecord.id,
                    )
                    .where(
                        DailyExecutionRecord.schedule_id == config.schedule_id,
                        DailyExecutionRecord.revision_id == config.revision_id,
                        DailyReportRecord.usable_until > now,
                    )
                    .order_by(DailyReportRecord.recorded_at.desc())
                    .limit(1)
                )
                if prior is not None and fingerprint(prior.report_json) != prior.content_hash:
                    raise DailyError("DAILY_REPORT_HASH_INVALID")
                prior_report = DailyReport.model_validate(prior.report_json) if prior else None
                previous = prior_report.evidence_diff.visible_ids if prior_report else ()
                diff = evidence_diff(
                    local.evidence,
                    as_of=now,
                    previous=previous,
                    baseline_report_id=prior.id if prior else None,
                )
                command = current.prepared.command
                scheduled = (
                    command.mode == "SCHEDULED_SHADOW"
                    and now.astimezone(MarketVenue(command.market).timezone).date()
                    == day.business_date
                )
                commands = []
                if scheduled:
                    for instrument_id in command.instrument_ids:
                        evidence_ids = tuple(
                            row.evidence_id
                            for row in local.evidence
                            if row.instrument_id == instrument_id and row.reason(now) is None
                        )
                        if not evidence_ids or local.quote_statuses[instrument_id] != "AVAILABLE":
                            continue
                        request_id = uuid5(execution_id, str(instrument_id))
                        commands.append(
                            AnalysisStart(
                                request_id=request_id,
                                portfolio_id=command.portfolio_id,
                                instrument_id=instrument_id,
                                model_profiles=command.model_profiles,
                                evidence_ids=evidence_ids[:100],
                                data_profile_ids=(),
                                market_source_name=command.quote_source_name,
                                allow_model_calls=True,
                                allow_data_calls=False,
                                runtime_authorization=RuntimeAuthorizationRef(
                                    kind="DAILY_SHADOW",
                                    schedule_id=config.schedule_id,
                                    revision_id=config.revision_id,
                                    authorization_version=config.version,
                                    authorization_hash=current.prepared.input_hash,
                                    intent_id=request_id,
                                ),
                            )
                        )
                execution = DailyExecutionRecord(
                    id=execution_id,
                    task_run_id=task.id,
                    schedule_id=config.schedule_id,
                    revision_id=config.revision_id,
                    authorization_version=config.version,
                    business_date=day.business_date,
                    business_as_of=day.close_at_utc,
                    as_of=now,
                    local_snapshot_json=local.model_dump(mode="json"),
                    input_hash=fingerprint(
                        {
                            "authorization": current.prepared.input_hash,
                            "version": current.version,
                            "business_as_of": day.close_at_utc.isoformat(),
                            "local": local.content_hash,
                        }
                    ),
                    **common(task.id),
                )
                uow.session.add(execution)
                await uow.session.flush()
                for analysis in commands:
                    payload = analysis_command_payload(analysis)
                    uow.session.add(
                        DailyAnalysisIntentRecord(
                            id=analysis.request_id,
                            execution_id=execution_id,
                            instrument_id=analysis.instrument_id,
                            revision_id=config.revision_id,
                            command_json=payload,
                            request_hash=fingerprint(payload),
                            **common(task.id),
                        )
                    )
                report = build_daily_report(
                    report_id=report_id,
                    task_run_id=task.id,
                    config=current,
                    business_date=day.business_date,
                    business_as_of=day.close_at_utc,
                    as_of=now,
                    recorded_at=now,
                    local=local,
                    diff=diff,
                    planned_count=len(commands),
                )
                payload = report.model_dump(mode="json")
                uow.session.add(
                    DailyReportRecord(
                        id=report_id,
                        execution_id=execution_id,
                        sequence=1,
                        phase=report.phase,
                        recorded_at=now,
                        usable_until=now + timedelta(days=command.retention_days),
                        report_json=payload,
                        content_hash=fingerprint(payload),
                        **common(task.id),
                    )
                )
                await uow.session.flush()
                for evidence_id in diff.visible_ids:
                    uow.session.add(
                        DailyReportEvidenceRecord(
                            report_id=report_id, evidence_id=evidence_id, purpose="LOCAL_VISIBLE"
                        )
                    )
                await emit(
                    uow.session,
                    "daily.report.created",
                    execution_id,
                    {
                        "report_id": str(report_id),
                        "phase": report.phase,
                        "intent_count": len(commands),
                        "auto_trade": False,
                    },
                    now,
                )

            try:
                result = await ReliableJobExecutor(self.sessions).execute(
                    task_name=f"daily:{config.schedule_id}",
                    scheduled_for=day.close_at_utc,
                    idempotency_key=key,
                    input_hash=fingerprint(
                        {
                            "revision": str(config.revision_id),
                            "authorization_hash": config.prepared.input_hash,
                            "date": str(day.business_date),
                        }
                    ),
                    handler=handler,
                )
            except Exception:
                continue  # Executor persists bounded local failures; no automatic paid retry.
            completed.append(result.task_run_id)
            # Only the transaction that just created an intent may submit once. On uncertain
            # response/restart, subsequent ticks read history and never create another paid run.
            if not result.reused:
                async with self.sessions() as session:
                    intents = (
                        await session.scalars(
                            select(DailyAnalysisIntentRecord)
                            .join(
                                DailyExecutionRecord,
                                DailyAnalysisIntentRecord.execution_id == DailyExecutionRecord.id,
                            )
                            .where(DailyExecutionRecord.task_run_id == result.task_run_id)
                        )
                    ).all()
                for intent in intents:
                    try:
                        run = await self.starter.start(
                            AnalysisStart.model_validate(intent.command_json)
                        )
                        async with self.sessions() as session, session.begin():
                            session.add(
                                DailyAnalysisBindingRecord(
                                    id=intent.id, analysis_run_id=run.run_id, **common(intent.id)
                                )
                            )
                            await emit(
                                session,
                                "daily.analysis.bound",
                                intent.id,
                                {"run_id": str(run.run_id)},
                                now,
                            )
                    except Exception:
                        # Intent remains visible as uncertain, never automatically re-enqueued.
                        continue
        await self.refresh_reports(now=now)
        return tuple(completed)

    async def refresh_reports(self, *, now: datetime) -> None:
        async with self.sessions() as session:
            identifiers = tuple(
                (
                    await session.scalars(
                        select(DailyExecutionRecord.id)
                        .order_by(DailyExecutionRecord.as_of.desc())
                        .limit(50)
                    )
                ).all()
            )
        for identifier in identifiers:
            async with self.sessions() as session, session.begin():
                execution = await session.get(
                    DailyExecutionRecord, identifier, with_for_update=True
                )
                if execution is None:
                    continue
                prior = await session.scalar(
                    select(DailyReportRecord)
                    .where(DailyReportRecord.execution_id == identifier)
                    .order_by(DailyReportRecord.sequence.desc())
                    .limit(1)
                )
                if prior is None or prior.usable_until <= now:
                    continue
                if fingerprint(prior.report_json) != prior.content_hash:
                    raise DailyError("DAILY_REPORT_HASH_INVALID")
                old = DailyReport.model_validate(prior.report_json)
                intents = (
                    await session.scalars(
                        select(DailyAnalysisIntentRecord).where(
                            DailyAnalysisIntentRecord.execution_id == identifier
                        )
                    )
                ).all()
                if not intents:
                    continue
                runs = []
                missing = []
                for intent in intents:
                    run = await self.analyses.find_request(intent.id)
                    if run is None:
                        missing.append(str(intent.id))
                        continue
                    if run.request_hash != intent.request_hash:
                        raise DailyError("DAILY_ANALYSIS_BINDING_HASH_MISMATCH")
                    binding = await session.get(DailyAnalysisBindingRecord, intent.id)
                    if binding is None:
                        session.add(
                            DailyAnalysisBindingRecord(
                                id=intent.id, analysis_run_id=run.run_id, **common(intent.id)
                            )
                        )
                    elif binding.analysis_run_id != run.run_id:
                        raise DailyError("DAILY_ANALYSIS_BINDING_HASH_MISMATCH")
                    runs.append(run)
                # Reuse this execution's frozen authorization, even if current config changes.
                from investment_os.application.daily_runtime import DailyConfiguration

                frozen = DailyConfiguration(
                    schedule_id=old.schedule_id,
                    revision_id=old.revision_id,
                    version=old.authorization_version,
                    enabled=True,
                    revoked=False,
                    enabled_since=execution.as_of,
                    prepared=old.authorization,
                )
                report = build_daily_report(
                    report_id=uuid4(),
                    task_run_id=execution.task_run_id,
                    config=frozen,
                    business_date=execution.business_date,
                    business_as_of=execution.business_as_of,
                    as_of=execution.as_of,
                    recorded_at=now,
                    local=old.local_inputs,
                    diff=old.evidence_diff,
                    planned_count=len(intents),
                    analyses=tuple(runs),
                )
                if missing:
                    from investment_os.application.daily_runtime import DailySection

                    report = report.model_copy(
                        update={
                            "phase": "DEGRADED",
                            "data_job_degraded": DailySection(
                                availability="DEGRADED",
                                messages=(
                                    "研究意图无队列结果; 未自动重提, 请核对未知费用。",
                                    *missing,
                                ),
                            ),
                        }
                    )
                if report.model_dump(
                    mode="json", exclude={"report_id", "recorded_at"}
                ) == old.model_dump(mode="json", exclude={"report_id", "recorded_at"}):
                    continue
                payload = report.model_dump(mode="json")
                session.add(
                    DailyReportRecord(
                        id=report.report_id,
                        execution_id=identifier,
                        sequence=prior.sequence + 1,
                        phase=report.phase,
                        recorded_at=now,
                        usable_until=prior.usable_until,
                        report_json=payload,
                        content_hash=fingerprint(payload),
                        **common(execution.id),
                    )
                )
                await session.flush()
                for run in runs:
                    session.add(
                        DailyReportAnalysisRecord(
                            report_id=report.report_id, analysis_run_id=run.run_id
                        )
                    )
                for evidence_id in report.evidence_diff.visible_ids:
                    session.add(
                        DailyReportEvidenceRecord(
                            report_id=report.report_id,
                            evidence_id=evidence_id,
                            purpose="LOCAL_VISIBLE",
                        )
                    )
                await emit(
                    session,
                    "daily.report.updated",
                    identifier,
                    {"report_id": str(report.report_id), "phase": report.phase},
                    now,
                )
