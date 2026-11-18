"""Bounded read-only weekly TaskRun audit from its original revision, without dispatch."""

import base64
import binascii
from datetime import date
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.complete_weekly_template import CompleteWeeklyTemplate
from investment_os.application.opportunities import FunnelQuery, OpportunityError
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.application.universe_snapshots import UniverseError
from investment_os.application.weekly_task_history import (
    WeeklyProtocol,
    WeeklyTaskCursor,
    WeeklyTaskDetail,
    WeeklyTaskPage,
    WeeklyTaskProvenance,
    WeeklyTaskSummary,
)
from investment_os.infrastructure.complete_scope import SqlCompleteScope
from investment_os.infrastructure.opportunities import SqlOpportunityStore, digest
from investment_os.infrastructure.persistence.calendar_models import CalendarImportRecord
from investment_os.infrastructure.persistence.models import EventLogRecord, TaskRunRecord
from investment_os.infrastructure.weekly_funnel_models import (
    WeeklyMemberRecord,
    WeeklyResultRecord,
    WeeklyRevisionRecord,
)


class SqlWeeklyTaskHistory:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], protocol: WeeklyProtocol):
        self.sessions, self.protocol = sessions, protocol
        self.task_prefix = "weekly-local:" if protocol == "1.0" else "weekly-complete:"
        self.key_prefix = "weekly-funnel" if protocol == "1.0" else "weekly-complete"

    def identity(self, task: TaskRunRecord) -> tuple[UUID | None, UUID | None, date | None]:
        try:
            schedule = UUID(task.task_name.removeprefix(self.task_prefix))
            kind, revision, week = task.idempotency_key.split(":")
            if kind != self.key_prefix:
                raise ValueError("different protocol")
            return schedule, UUID(revision), date.fromisoformat(week)
        except (ValueError, TypeError):
            return None, None, None

    def summary(self, task: TaskRunRecord, result: WeeklyResultRecord | None) -> WeeklyTaskSummary:
        schedule, revision, week = self.identity(task)
        unknowns = ["ATTEMPT_TIMELINE_NOT_RECORDED"]
        if revision is None:
            unknowns.append("LEGACY_TASK_IDENTITY_NOT_PROVIDED")
        if result and (
            result.revision_id != revision
            or result.week_start != week
            or result.schema_version != self.protocol
        ):
            result = None
            unknowns.append("RESULT_REFERENCE_MISMATCH")
        if result is None:
            unknowns.append("NO_COMMITTED_WEEKLY_RESULT")
        reason = (task.error_json or {}).get("type")
        return WeeklyTaskSummary(
            protocol=self.protocol,
            task_run_id=task.id,
            schedule_id=schedule,
            revision_id=revision,
            week_start=week,
            scheduled_for=task.scheduled_for,
            created_at=task.created_at,
            started_at=task.started_at,
            finished_at=task.finished_at,
            task_status=task.status,
            attempt=task.attempt,
            reason_code=result.reason_code
            if result
            else reason
            if isinstance(reason, str)
            else None,
            input_hash=task.input_hash,
            result_status=result.status if result else None,
            as_of=result.as_of if result else None,
            candidate_count=result.candidate_count if result else None,
            unknowns=tuple(unknowns),
        )

    async def tasks(self, cursor: str | None = None) -> WeeklyTaskPage:
        statement = (
            select(TaskRunRecord, WeeklyResultRecord)
            .outerjoin(WeeklyResultRecord, WeeklyResultRecord.task_run_id == TaskRunRecord.id)
            .where(TaskRunRecord.task_name.startswith(self.task_prefix))
        )
        if cursor is not None:
            try:
                if len(cursor) > 1024:
                    raise ValueError("cursor too long")
                boundary = WeeklyTaskCursor.model_validate_json(
                    base64.b64decode(cursor, altchars=b"-_", validate=True)
                )
                if boundary.protocol != self.protocol:
                    raise ValueError("wrong protocol cursor")
            except (ValueError, binascii.Error):
                raise OpportunityError("WEEKLY_TASK_CURSOR_INVALID") from None
            statement = statement.where(
                tuple_(TaskRunRecord.created_at, TaskRunRecord.id)
                < tuple_(literal(boundary.created_at), literal(boundary.task_run_id))
            )
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    statement.order_by(
                        TaskRunRecord.created_at.desc(), TaskRunRecord.id.desc()
                    ).limit(51)
                )
            ).all()
            items = tuple(self.summary(task, result) for task, result in rows[:50])
            next_cursor = None
            if len(rows) > 50:
                last = rows[49][0]
                next_cursor = base64.urlsafe_b64encode(
                    WeeklyTaskCursor(
                        protocol=self.protocol, created_at=last.created_at, task_run_id=last.id
                    )
                    .model_dump_json()
                    .encode()
                ).decode()
            return WeeklyTaskPage(protocol=self.protocol, items=items, next_cursor=next_cursor)

    async def provenance(
        self, session: AsyncSession, summary: WeeklyTaskSummary
    ) -> WeeklyTaskProvenance | None:
        if summary.revision_id is None:
            return None
        revision = await session.get(WeeklyRevisionRecord, summary.revision_id)
        if (
            revision is None
            or revision.schedule_id != summary.schedule_id
            or revision.schema_version != self.protocol
        ):
            return None
        from investment_os.infrastructure.opportunity_schedule import revision_payload

        if fingerprint(revision_payload(revision)) != revision.content_hash:
            return None
        try:
            template = (
                FunnelQuery.model_validate(revision.template_json)
                if self.protocol == "1.0"
                else CompleteWeeklyTemplate.model_validate(revision.template_json)
            )
        except ValidationError:
            return None
        members = set(
            await session.scalars(
                select(WeeklyMemberRecord.instrument_id).where(
                    WeeklyMemberRecord.revision_id == revision.id
                )
            )
        )
        if (
            members != set(template.instrument_ids)
            or fingerprint(
                {
                    "revision": str(revision.id),
                    "hash": revision.content_hash,
                    "week": str(summary.week_start),
                }
            )
            != summary.input_hash
        ):
            return None
        source = await session.get(CalendarImportRecord, revision.calendar_import_id)
        if source and (
            source.content_hash != revision.calendar_hash or source.venue != revision.venue
        ):
            source = None
        return WeeklyTaskProvenance(
            name=revision.name,
            venue=revision.venue,
            revision_hash=revision.content_hash,
            calendar_import_id=revision.calendar_import_id,
            calendar_hash=revision.calendar_hash,
            calendar_source=source.source_name if source else None,
            calendar_version=source.source_version if source else None,
            template_run_id=revision.template_run_id,
            source_name=template.scope_name,
            source_locator=template.scope_locator,
            quote_source_name=template.quote_source_name,
            fact_source_name=template.fact_source_name,
            coverage_start=revision.coverage_start,
            coverage_end=revision.coverage_end,
            snapshot_id=template.snapshot_id
            if isinstance(template, CompleteWeeklyTemplate)
            else None,
            snapshot_hash=template.snapshot_hash
            if isinstance(template, CompleteWeeklyTemplate)
            else None,
        )

    async def task(self, task_run_id: UUID) -> WeeklyTaskDetail:
        async with self.sessions() as session:
            row = (
                await session.execute(
                    select(TaskRunRecord, WeeklyResultRecord)
                    .outerjoin(
                        WeeklyResultRecord, WeeklyResultRecord.task_run_id == TaskRunRecord.id
                    )
                    .where(
                        TaskRunRecord.id == task_run_id,
                        TaskRunRecord.task_name.startswith(self.task_prefix),
                    )
                )
            ).one_or_none()
            if row is None:
                raise OpportunityError("WEEKLY_TASK_NOT_FOUND_OR_WRONG_PROTOCOL")
            task, result = row
            summary = self.summary(task, result)
            provenance = await self.provenance(session, summary)
            unknowns = list(summary.unknowns)
            if provenance is None:
                unknowns.append("ORIGINAL_REVISION_MISSING_OR_UNVERIFIED")
            elif provenance.calendar_source is None:
                unknowns.append("ORIGINAL_CALENDAR_SOURCE_NOT_PROVIDED")
            funnel_id = funnel_hash = None
            if (
                result
                and result.funnel_run_id
                and provenance
                and "RESULT_REFERENCE_MISMATCH" not in unknowns
            ):
                event = (
                    await session.get(EventLogRecord, result.funnel_event_id)
                    if result.funnel_event_id
                    else None
                )
                expected_kind = (
                    "opportunity_funnel_run"
                    if self.protocol == "1.0"
                    else "opportunity_complete_scope_v2"
                )
                try:
                    if (
                        event is None
                        or event.aggregate_id != result.funnel_run_id
                        or event.aggregate_type != expected_kind
                    ):
                        raise OpportunityError("WEEKLY_ARTIFACT_REFERENCE_INVALID")
                    run = (
                        await SqlOpportunityStore(self.sessions).get_run(result.funnel_run_id)
                        if self.protocol == "1.0"
                        else await SqlCompleteScope(self.sessions).get_complete(
                            result.funnel_run_id
                        )
                    )
                    if run is None:
                        raise OpportunityError("WEEKLY_ARTIFACT_REFERENCE_INVALID")
                    funnel_id = result.funnel_run_id
                    funnel_hash = digest(run.model_dump(mode="json"))
                except (OpportunityError, UniverseError):
                    unknowns.append("ORIGINAL_ARTIFACT_MISSING_OR_UNVERIFIED")
            else:
                unknowns.append("NO_VERIFIED_FUNNEL_ARTIFACT")
            return WeeklyTaskDetail(
                **summary.model_dump(exclude={"unknowns"}),
                provenance=provenance,
                funnel_run_id=funnel_id,
                funnel_hash=funnel_hash,
                unknowns=tuple(unknowns),
            )
