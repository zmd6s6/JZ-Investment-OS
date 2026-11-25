"""Human content-only Thesis transaction with immutable command receipts."""

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.thesis import (
    semantic_diff,
    thesis_content_hash,
    thesis_semantic_diff_payload,
)
from investment_os.application.thesis_workspace import (
    SavedThesis,
    ThesisCommand,
    ThesisDraft,
    ThesisEvidence,
    ThesisPreview,
    ThesisReceipt,
    ThesisWorkspace,
)
from investment_os.domain.enums import ThesisState
from investment_os.domain.thesis import ThesisVersion
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    EventLogRecord,
    EvidenceRecord,
    InstrumentRecord,
    InvestmentThesisRecord,
    OutboxEventRecord,
    ThesisVersionRecord,
)
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork
from investment_os.infrastructure.thesis_engine import SqlAlchemyThesisWriter, _content_from_record
from investment_os.infrastructure.thesis_workspace_models import ThesisCommandReceiptRecord


def evidence_problem(row: EvidenceRecord, instrument_id: UUID, now: datetime) -> str | None:
    if row.instrument_id not in (None, instrument_id):
        return "THESIS_EVIDENCE_WRONG_INSTRUMENT"
    # Neutral evidence follows the existing Analysis scope: only explicit neutral rows.
    if max(row.observed_at, row.effective_at, row.available_at, row.ingested_at) > now:
        return "THESIS_EVIDENCE_FUTURE"
    if row.expires_at is not None and row.expires_at <= now:
        return "THESIS_EVIDENCE_EXPIRED"
    if not 0 < row.quality_score <= 1 or row.freshness_status != "FRESH":
        return "THESIS_EVIDENCE_INVALID"
    return None


def saved(row: ThesisVersionRecord) -> SavedThesis:
    from investment_os.application.thesis import thesis_content_payload

    content = _content_from_record(row)
    if thesis_content_hash(content) != row.content_hash:
        raise ValueError("THESIS_VERSION_CORRUPT")
    return SavedThesis(
        thesis_id=row.thesis_id,
        version_id=row.id,
        version=row.version,
        parent_version_id=row.parent_version_id,
        content_hash=row.content_hash,
        created_at=row.created_at,
        draft=ThesisDraft.model_validate(thesis_content_payload(content)),
        semantic_diff=row.metadata_json.get("semantic_diff"),
    )


class SqlThesisWorkspace:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        now: Callable[[], datetime] | None = None,
    ):
        self._sessions = sessions
        self._now = now or (lambda: datetime.now(UTC))

    async def read(self, instrument_id: UUID) -> ThesisWorkspace:
        async with self._sessions() as session:
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            if await session.get(InstrumentRecord, instrument_id) is None:
                raise ValueError("THESIS_INSTRUMENT_NOT_FOUND")
            thesis = await session.scalar(
                select(InvestmentThesisRecord).where(
                    InvestmentThesisRecord.instrument_id == instrument_id
                )
            )
            versions = (
                []
                if thesis is None
                else list(
                    (
                        await session.scalars(
                            select(ThesisVersionRecord)
                            .where(ThesisVersionRecord.thesis_id == thesis.id)
                            .order_by(ThesisVersionRecord.version.desc())
                        )
                    ).all()
                )
            )
            # Original version sources remain inspectable outside the recent picker.
            linked = {
                identifier for v in versions for identifier in _content_from_record(v).evidence_ids
            }
            newest = (
                select(EvidenceRecord.id)
                .where(
                    or_(
                        EvidenceRecord.instrument_id == instrument_id,
                        EvidenceRecord.instrument_id.is_(None),
                    )
                )
                .order_by(EvidenceRecord.ingested_at.desc(), EvidenceRecord.id)
                .limit(100)
            )
            rows = (
                await session.scalars(
                    select(EvidenceRecord)
                    .where(or_(EvidenceRecord.id.in_(newest), EvidenceRecord.id.in_(linked)))
                    .order_by(EvidenceRecord.ingested_at.desc(), EvidenceRecord.id)
                )
            ).all()
            now = self._now()
            current = next(
                (v for v in versions if thesis is not None and v.id == thesis.current_version_id),
                None,
            )
            if thesis is not None and current is None:
                raise ValueError("THESIS_CURRENT_VERSION_MISSING")
            return ThesisWorkspace(
                instrument_id=instrument_id,
                current=saved(current) if current else None,
                history=tuple(saved(v) for v in versions),
                evidence=tuple(
                    ThesisEvidence(
                        evidence_id=r.id,
                        source_name=r.source_name,
                        source_locator=r.source_locator,
                        observed_at=r.observed_at,
                        effective_at=r.effective_at,
                        available_at=r.available_at,
                        ingested_at=r.ingested_at,
                        expires_at=r.expires_at,
                        content_hash=r.content_hash,
                        quality_score=str(r.quality_score),
                        eligible=evidence_problem(r, instrument_id, now) is None,
                        reason=evidence_problem(r, instrument_id, now),
                        excerpt=json.dumps(r.payload_json, ensure_ascii=False)[:1000],
                    )
                    for r in rows
                ),
            )

    async def _inputs(
        self, uow: SqlAlchemyUnitOfWork, command: ThesisCommand
    ) -> tuple[InvestmentThesisRecord | None, ThesisVersionRecord | None, Sequence[EvidenceRecord]]:
        if await uow.session.get(InstrumentRecord, command.instrument_id) is None:
            raise ValueError("THESIS_INSTRUMENT_NOT_FOUND")
        thesis = await uow.theses.get_by_instrument(command.instrument_id)
        current = (
            None
            if thesis is None or thesis.current_version_id is None
            else await uow.thesis_versions.get(thesis.current_version_id)
        )
        if thesis is not None and current is None:
            raise ValueError("THESIS_CURRENT_VERSION_MISSING")
        if (current is None and command.expected_version_id is not None) or (
            current is not None
            and (
                current.id != command.expected_version_id
                or current.content_hash != command.expected_content_hash
            )
        ):
            raise ValueError("THESIS_BASELINE_CONFLICT")
        if command.draft.state != (
            ThesisState.UNKNOWN if current is None else ThesisState(current.thesis_state)
        ):
            raise ValueError("THESIS_STATE_CHANGE_FORBIDDEN")
        rows = (
            await uow.session.scalars(
                select(EvidenceRecord).where(
                    EvidenceRecord.id.in_(command.draft.domain().evidence_ids)
                )
            )
        ).all()
        return thesis, current, rows

    def _validate(self, command: ThesisCommand, rows: Sequence[EvidenceRecord]) -> datetime:
        now = self._now()
        if set(command.draft.domain().evidence_ids) != {r.id for r in rows}:
            raise ValueError("THESIS_EVIDENCE_MISSING")
        for row in rows:
            problem = evidence_problem(row, command.instrument_id, now)
            if problem:
                raise ValueError(problem)
        return now

    async def preview(self, command: ThesisCommand) -> ThesisPreview:
        async with SqlAlchemyUnitOfWork(self._sessions) as uow:
            _, current, rows = await self._inputs(uow, command)
            now = self._validate(command, rows)
            diff = (
                None
                if current is None
                else semantic_diff(_content_from_record(current), command.draft.domain())
            )
            return ThesisPreview(
                command_hash=command.canonical_hash(),
                content_hash=thesis_content_hash(command.draft.domain()),
                material=diff is None or diff.is_material,
                differences={"initial_creation": True}
                if diff is None
                else thesis_semantic_diff_payload(diff),
                checked_at=now,
            )

    async def save(self, command: ThesisCommand) -> ThesisReceipt:
        command_hash = command.canonical_hash()
        async with SqlAlchemyUnitOfWork(self._sessions) as uow:
            # Request lock precedes instrument lock; both held through commit.
            for key in (
                f"thesis-request:{command.request_id}",
                f"thesis-instrument:{command.instrument_id}",
            ):
                await uow.session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key}
                )
            prior = await uow.session.get(ThesisCommandReceiptRecord, command.request_id)
            if prior is not None:
                if (
                    prior.command_hash != command_hash
                    or prior.instrument_id != command.instrument_id
                ):
                    raise ValueError("THESIS_REQUEST_CONFLICT")
                return ThesisReceipt.model_validate(prior.result_json)
            thesis, current, rows = await self._inputs(uow, command)
            now = self._validate(command, rows)
            content = command.draft.domain()
            diff = (
                None if current is None else semantic_diff(_content_from_record(current), content)
            )
            created = diff is None or diff.is_material
            correlation = command.request_id
            if created:
                if thesis is None:
                    thesis = InvestmentThesisRecord(
                        instrument_id=command.instrument_id,
                        status=content.state.value,
                        current_version_id=None,
                        created_at=now,
                        created_by=command.actor_name.strip(),
                        correlation_id=correlation,
                        metadata_json={},
                    )
                    await uow.theses.add(thesis)
                version = ThesisVersion(
                    id=uuid4(),
                    thesis_id=thesis.id,
                    version=1 if current is None else current.version + 1,
                    parent_version_id=None if current is None else current.id,
                    content_hash=thesis_content_hash(content),
                    content=content,
                )
                record = SqlAlchemyThesisWriter._version_record(
                    version,
                    created_at=now,
                    evaluation_time=now,
                    correlation_id=correlation,
                    diff_payload=None if diff is None else thesis_semantic_diff_payload(diff),
                )
                record.created_by = command.actor_name.strip()
                await uow.thesis_versions.append(record)
                await uow.thesis_versions.link_evidence(record.id, content.evidence_ids)
                await uow.theses.update_current_version(
                    thesis.id,
                    expected_version=thesis.version,
                    current_version_id=record.id,
                    status=content.state.value,
                )
            else:
                assert current is not None
                record = current
            receipt = ThesisReceipt(
                request_id=command.request_id,
                instrument_id=command.instrument_id,
                command_hash=command_hash,
                created=created,
                saved=saved(record),
            )
            operation = "thesis.human_revision.saved" if created else "thesis.human_revision.noop"
            payload = receipt.model_dump(mode="json")
            await uow.audit.append(
                AuditLogRecord(
                    actor_type="HUMAN",
                    actor_id=command.actor_name.strip(),
                    operation=operation,
                    entity_type="ThesisVersion",
                    entity_id=record.id,
                    before_hash=None if current is None else current.content_hash,
                    after_hash=record.content_hash,
                    ip_or_runtime_ref="authenticated-local-api",
                    occurred_at=now,
                    correlation_id=correlation,
                    created_by=command.actor_name.strip(),
                    metadata_json={"request_id": str(command.request_id)},
                )
            )
            event = EventLogRecord(
                id=uuid4(),
                event_type=operation,
                aggregate_type="Thesis",
                aggregate_id=record.thesis_id,
                payload_json=payload,
                occurred_at=now,
                correlation_id=correlation,
                created_by=command.actor_name.strip(),
            )
            await uow.events.append(event)
            await uow.outbox.add(
                OutboxEventRecord(
                    event_id=event.id,
                    topic=operation,
                    payload_json=payload,
                    created_by=command.actor_name.strip(),
                    correlation_id=correlation,
                )
            )
            uow.session.add(
                ThesisCommandReceiptRecord(
                    request_id=command.request_id,
                    instrument_id=command.instrument_id,
                    version_id=record.id,
                    command_hash=command_hash,
                    result_json=payload,
                    created_at=now,
                    created_by=command.actor_name.strip(),
                    correlation_id=correlation,
                )
            )
            await uow.session.flush()
            # Final UTC check after awaited operations; failure rolls back every effect.
            self._validate(command, rows)
            await uow.commit()
            return receipt
