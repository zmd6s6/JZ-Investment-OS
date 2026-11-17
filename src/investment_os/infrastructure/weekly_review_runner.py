"""Weekly local execution commits TaskRun, frozen report and provenance together."""

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.daily_runtime import evidence_diff
from investment_os.application.market_data import MarketDataSnapshot
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.application.schedule import MarketVenue
from investment_os.application.weekly_review import (
    WeeklyConfiguration,
    WeeklyError,
    WeeklyHoldingReview,
    WeeklyReport,
    complete_weeks,
)
from investment_os.infrastructure.persistence.jobs import ReliableJobExecutor
from investment_os.infrastructure.persistence.models import TaskRunRecord
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork
from investment_os.infrastructure.weekly_review_models import (
    WeeklyConfigurationRecord,
    WeeklyReportEvidenceRecord,
    WeeklyReportRecord,
    WeeklyReportReferenceRecord,
)
from investment_os.infrastructure.weekly_review_reader import SqlWeeklyReader
from investment_os.infrastructure.weekly_review_scope import capture
from investment_os.infrastructure.weekly_review_store import (
    common,
    configuration,
    emit,
    verify_report,
)


class WeeklyReviewRunner:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        reader: SqlWeeklyReader,
        *,
        clock: Callable[[], datetime] | None = None,
        max_periods: int = 4,
    ):
        self.sessions, self.reader = sessions, reader
        self.clock = clock or (lambda: datetime.now(UTC))
        if not 1 <= max_periods <= 4:
            raise ValueError("weekly max_periods must be between 1 and 4")
        self.max_periods = max_periods

    async def dispatch_due(self, *, now: datetime) -> tuple[UUID, ...]:
        if now.utcoffset() is None:
            raise WeeklyError("WEEKLY_TIMEZONE_REQUIRED")
        plans = []
        async with self.sessions() as session, session.begin():
            # A singleton row serializes bounded scans across Worker processes/restarts.
            # It records traversal only, never authorization or report state.
            await session.execute(
                text(
                    "INSERT INTO weekly_scan_cursor (id, after_id) VALUES (1, NULL) "
                    "ON CONFLICT (id) DO NOTHING"
                )
            )
            scan_after = await session.scalar(
                text("SELECT after_id FROM weekly_scan_cursor WHERE id = 1 FOR UPDATE")
            )
            statement = select(WeeklyConfigurationRecord).where(
                WeeklyConfigurationRecord.enabled.is_(True),
                WeeklyConfigurationRecord.revoked.is_(False),
            )
            if scan_after is not None:
                statement = statement.where(WeeklyConfigurationRecord.id > scan_after)
            rows = (
                await session.scalars(statement.order_by(WeeklyConfigurationRecord.id).limit(50))
            ).all()
            if not rows and scan_after is not None:
                # Wrap immediately without examining more than 50 configurations.
                rows = (
                    await session.scalars(
                        select(WeeklyConfigurationRecord)
                        .where(
                            WeeklyConfigurationRecord.enabled.is_(True),
                            WeeklyConfigurationRecord.revoked.is_(False),
                        )
                        .order_by(WeeklyConfigurationRecord.id)
                        .limit(50)
                    )
                ).all()
            # Advance only through the last actually examined row, even when max_periods is hit.
            last_examined = None
            for pointer in rows:
                last_examined = pointer.id
                try:
                    config = await configuration(session, pointer, now)
                except (WeeklyError, ValueError):
                    # A corrupt source cannot pin the fair cursor forever. No authorization
                    # or task is invented; API reads expose the source failure.
                    continue
                if config.blocker or config.prepared is None:
                    continue
                command = config.prepared.command
                for start, end in complete_weeks(
                    command.coverage_start, command.coverage_end, now, command.market
                ):
                    if (
                        await session.scalar(
                            select(WeeklyReportRecord.id).where(
                                WeeklyReportRecord.schedule_id == pointer.id,
                                WeeklyReportRecord.period_start == start,
                            )
                        )
                        is None
                    ):
                        key = f"weekly:{config.schedule_id}:{config.revision_id}:{start:%Y-%m-%d}"
                        prior_task = await session.scalar(
                            select(TaskRunRecord).where(TaskRunRecord.idempotency_key == key)
                        )
                        if prior_task is None or prior_task.attempt < 3:
                            plans.append((config, start, end))
                    if len(plans) >= self.max_periods:
                        break
                if len(plans) >= self.max_periods:
                    break
            await session.execute(
                text("UPDATE weekly_scan_cursor SET after_id = :after_id WHERE id = 1"),
                {"after_id": last_examined},
            )
        completed = []
        for config, start, end in plans:
            if config.prepared is None:
                continue
            key = f"weekly:{config.schedule_id}:{config.revision_id}:{start:%Y-%m-%d}"

            async def handler(
                uow: SqlAlchemyUnitOfWork,
                config: WeeklyConfiguration = config,
                start: date = start,
                end: date = end,
                key: str = key,
            ) -> None:
                pointer = await uow.session.get(
                    WeeklyConfigurationRecord, config.schedule_id, with_for_update=True
                )
                if pointer is None:
                    raise WeeklyError("WEEKLY_CONFIGURATION_NOT_FOUND")
                current = await configuration(uow.session, pointer, now)
                if (
                    current.blocker
                    or current.prepared is None
                    or current.version != config.version
                    or current.revision_id != config.revision_id
                ):
                    raise WeeklyError(current.blocker or "WEEKLY_VERSION_CHANGED")
                # Config -> portfolio/member -> calendar lock order matches the Daily reader.
                prepared, days = await capture(
                    uow.session, current.prepared.command, now, lock=True
                )
                if prepared.content_hash != current.prepared.content_hash:
                    raise WeeklyError("WEEKLY_SCOPE_OR_CALENDAR_CHANGED")
                if await uow.session.scalar(
                    select(WeeklyReportRecord.id).where(
                        WeeklyReportRecord.schedule_id == config.schedule_id,
                        WeeklyReportRecord.period_start == start,
                    )
                ):
                    raise WeeklyError("WEEKLY_PERIOD_ALREADY_COMMITTED")
                task = await uow.task_runs.get_by_idempotency_key(key)
                if task is None:
                    raise WeeklyError("WEEKLY_TASK_REFERENCE_MISSING")
                sessions_in_week = tuple(day for day in days if start <= day.business_date <= end)
                prior_row = await uow.session.scalar(
                    select(WeeklyReportRecord)
                    .where(
                        WeeklyReportRecord.schedule_id == config.schedule_id,
                        WeeklyReportRecord.revision_id == config.revision_id,
                        WeeklyReportRecord.period_start < start,
                        WeeklyReportRecord.usable_until > now,
                        WeeklyReportRecord.phase != "CLOSED_WEEK_SKIPPED",
                        WeeklyReportRecord.report_json["local_inputs"].astext.is_not(None),
                    )
                    # A skipped closed week records no portfolio/evidence capture.
                    # Filter before LIMIT so an earlier real capture remains reachable.
                    .order_by(WeeklyReportRecord.period_start.desc())
                    .limit(1)
                )
                prior = verify_report(prior_row, now) if prior_row else None
                # Replays of historical weeks never claim to restore historical ledger state.
                knowledge_as_of = self.clock()
                local = numbers = None
                holdings: tuple[WeeklyHoldingReview, ...] = ()
                quotes: tuple[MarketDataSnapshot, ...] = ()
                diff = None
                if sessions_in_week:
                    local, holdings, numbers, quotes = await self.reader.read(
                        uow.session, current.prepared, knowledge_as_of, prior
                    )
                    diff = evidence_diff(
                        local.evidence,
                        as_of=knowledge_as_of,
                        previous=prior.evidence_diff.visible_ids
                        if prior and prior.evidence_diff
                        else (),
                        baseline_report_id=prior.report_id if prior else None,
                    )
                report_id = uuid4()
                usable_until = knowledge_as_of + timedelta(days=prepared.command.retention_days)
                if local and diff:
                    usable_until = min(
                        [usable_until]
                        + [
                            row.expires_at
                            for row in local.evidence
                            if row.evidence_id in diff.visible_ids and row.expires_at is not None
                        ]
                    )
                report = WeeklyReport(
                    report_id=report_id,
                    task_run_id=task.id,
                    schedule_id=config.schedule_id,
                    revision_id=current.revision_id,
                    authorization_version=current.version,
                    period_start=start,
                    period_end=end,
                    business_as_of=sessions_in_week[-1].close_at_utc if sessions_in_week else None,
                    knowledge_as_of=knowledge_as_of,
                    recorded_at=self.clock(),
                    usable_until=usable_until,
                    phase="DEGRADED" if sessions_in_week else "CLOSED_WEEK_SKIPPED",
                    authorization=current.prepared,
                    local_inputs=local,
                    evidence_diff=diff,
                    baseline_report_id=prior.report_id if prior else None,
                    baseline_status="COMPARABLE_BASELINE" if prior else "FIRST_RUN_NO_BASELINE",
                    holdings=holdings,
                    valuation=numbers,
                    quotes=quotes,
                    unknowns=(
                        "MACRO_AND_INDUSTRY_PANORAMA_NOT_PROVIDED",
                        "CORRELATION_AND_CAPITAL_EFFICIENCY_NOT_PROVIDED",
                        "NO_NEW_INVESTMENT_JUDGMENT_OR_APPROVAL",
                        "CURRENT_BOOK_NOT_HISTORICAL_WEEK_END_SNAPSHOT",
                        "HISTORICAL_RETURNS_NOT_PROVIDED",
                        "CALENDAR_CLOSED_DAYS_SOURCE_DECLARED_NOT_EXCHANGE_VERIFIED",
                    )
                    if sessions_in_week
                    else ("EXPLICIT_COMPLETE_CLOSED_WEEK_NO_RESEARCH",),
                    recovery=(
                        "核对显式本地资料、行情来源和日期; 补充资料后下一个获准完整周重新复核。",
                        "失败最多三次本地重试; 修正来源须保存新暂停授权并重新确认启用。",
                        "到期停止使用正文并保留审计。原报告只读重放, 不重新取数或调用模型。",
                    ),
                    content_hash="0" * 64,
                )
                report = report.model_copy(
                    update={
                        "content_hash": fingerprint(
                            report.model_dump(mode="json", exclude={"content_hash"})
                        )
                    }
                )
                # Permission time is checked again after all awaited local input capture.
                final_now = self.clock()
                if not prepared.command.valid_from <= final_now < prepared.command.valid_until:
                    raise WeeklyError("WEEKLY_AUTHORIZATION_EXPIRED_DURING_CAPTURE")
                uow.session.add(
                    WeeklyReportRecord(
                        id=report_id,
                        task_run_id=task.id,
                        schedule_id=config.schedule_id,
                        revision_id=current.revision_id,
                        authorization_version=current.version,
                        period_start=start,
                        period_end=end,
                        business_as_of=report.business_as_of,
                        knowledge_as_of=report.knowledge_as_of,
                        recorded_at=report.recorded_at,
                        usable_until=report.usable_until,
                        baseline_report_id=report.baseline_report_id,
                        phase=report.phase,
                        report_json=report.model_dump(mode="json"),
                        content_hash=report.content_hash,
                        **common(report_id),
                    )
                )
                await uow.session.flush()
                if diff:
                    uow.session.add_all(
                        [
                            WeeklyReportEvidenceRecord(report_id=report_id, evidence_id=identifier)
                            for identifier in diff.visible_ids
                        ]
                    )
                for holding in holdings:
                    for ref in holding.references:
                        column = {
                            "THESIS": "thesis_id",
                            "ANALYSIS": "analysis_run_id",
                            "RISK": "risk_id",
                            "DECISION": "decision_id",
                        }[ref.kind]
                        uow.session.add(
                            WeeklyReportReferenceRecord(
                                report_id=report_id,
                                kind=ref.kind,
                                record_id=ref.record_id,
                                instrument_id=ref.instrument_id,
                                content_hash=ref.content_hash,
                                **{column: ref.record_id},
                            )
                        )
                await emit(
                    uow.session,
                    "weekly.report",
                    report_id,
                    dict(report_hash=report.content_hash, task_run_id=str(task.id)),
                    report.recorded_at,
                )

            try:
                result = await ReliableJobExecutor(self.sessions, now=lambda: now).execute(
                    task_name="weekly_portfolio_review",
                    scheduled_for=datetime.combine(
                        end + timedelta(days=1),
                        time.min,
                        tzinfo=MarketVenue(config.prepared.command.market).timezone,
                    ).astimezone(UTC),
                    idempotency_key=key,
                    input_hash=config.prepared.content_hash,
                    handler=handler,
                )
                completed.append(result.task_run_id)
            except Exception:
                # ReliableJobExecutor has rolled back partial artifacts and recorded sanitized
                # bounded failure metadata. The UI exposes that real attempt, never success.
                continue
        return tuple(completed)
