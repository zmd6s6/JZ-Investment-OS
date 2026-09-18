"""Transactional writer for immutable, evidence-backed Thesis versions."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.thesis import (
    MetricObservation,
    ThesisInvalidationEvaluation,
    evaluate_invalidation,
    thesis_content_hash,
    thesis_content_payload,
)
from investment_os.domain.thesis import ThesisContent, ThesisVersion
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.persistence.models import (
    InvestmentThesisRecord,
    ThesisVersionEvidenceRecord,
    ThesisVersionRecord,
)
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork


@dataclass(frozen=True, slots=True)
class ThesisWriteResult:
    """The stored immutable version, or an unchanged current version."""

    thesis_id: UUID
    thesis_version_id: UUID
    version: int
    created: bool


@dataclass(frozen=True, slots=True)
class ThesisInvalidationWriteResult:
    """A persisted invalidation proposal, never a Decision or an order."""

    evaluation: ThesisInvalidationEvaluation
    thesis_write: ThesisWriteResult | None


@dataclass(frozen=True, slots=True)
class ThesisVersionRead:
    """A detached, immutable read model for internal API presentation."""

    instrument_id: UUID
    thesis_id: UUID
    version_id: UUID
    version: int
    parent_version_id: UUID | None
    state: str
    summary: str
    pillars: object
    catalysts: object
    risks: object
    invalidation_conditions: object
    monitoring_conditions: object
    change_reason: str
    evidence_ids: tuple[UUID, ...]
    created_at: datetime


class SqlAlchemyThesisWriter:
    """Create and advance Thesis history without any Decision or execution behavior."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        now: Callable[[], datetime],
    ) -> None:
        self._session_factory = session_factory
        self._now = now

    async def write(
        self,
        *,
        instrument_id: UUID,
        content: ThesisContent,
        as_of: datetime,
        correlation_id: UUID | None = None,
        expected_current_content_hash: str | None = None,
    ) -> ThesisWriteResult:
        """Append a material version after validating all referenced Evidence at ``as_of``.

        A canonical content hash makes semantically equal inputs idempotent.  The current Thesis
        pointer is advanced with its optimistic version in the same transaction as the immutable
        version and normalized evidence links.
        """

        evaluation_time = UtcTimestamp(as_of).value
        created_at = UtcTimestamp(self._now()).value
        correlation = correlation_id or uuid4()
        evidence_ids = content.evidence_ids
        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            available_ids = await uow.evidence.available_ids(
                evidence_ids,
                instrument_id=instrument_id,
                as_of=evaluation_time,
            )
            missing_ids = tuple(sorted(set(evidence_ids) - available_ids, key=str))
            if missing_ids:
                raise ApplicationError(
                    ApplicationErrorCode.EVIDENCE_REFERENCE_UNAVAILABLE,
                    "Thesis content references Evidence unavailable for the requested business "
                    "time",
                    details={"evidence_ids": [str(evidence_id) for evidence_id in missing_ids]},
                )

            content_hash = thesis_content_hash(content)
            thesis = await uow.theses.get_by_instrument(instrument_id)
            if thesis is None:
                thesis = InvestmentThesisRecord(
                    instrument_id=instrument_id,
                    status=content.state.value,
                    current_version_id=None,
                    created_at=created_at,
                    created_by="thesis_engine",
                    correlation_id=correlation,
                    causation_id=None,
                    metadata_json={},
                )
                await uow.theses.add(thesis)
                version_number = 1
                parent_version_id = None
            else:
                if thesis.current_version_id is None:
                    raise ApplicationError(
                        ApplicationErrorCode.THESIS_CURRENT_VERSION_MISSING,
                        "an existing Thesis must have an immutable current version",
                        details={"thesis_id": str(thesis.id)},
                    )
                current = await uow.thesis_versions.get(thesis.current_version_id)
                if current is None:
                    raise ApplicationError(
                        ApplicationErrorCode.THESIS_CURRENT_VERSION_MISSING,
                        "the Thesis current version record does not exist",
                        details={"thesis_id": str(thesis.id)},
                    )
                if (
                    expected_current_content_hash is not None
                    and current.content_hash != expected_current_content_hash
                ):
                    raise ApplicationError(
                        ApplicationErrorCode.THESIS_CURRENT_VERSION_STALE,
                        "the Thesis changed before its invalidation proposal could be persisted",
                        details={"thesis_id": str(thesis.id)},
                    )
                if current.content_hash == content_hash:
                    return ThesisWriteResult(
                        thesis_id=thesis.id,
                        thesis_version_id=current.id,
                        version=current.version,
                        created=False,
                    )
                version_number = current.version + 1
                parent_version_id = current.id

            version_id = uuid4()
            version = ThesisVersion(
                id=version_id,
                thesis_id=thesis.id,
                version=version_number,
                parent_version_id=parent_version_id,
                content_hash=content_hash,
                content=content,
            )
            record = self._version_record(
                version,
                created_at=created_at,
                evaluation_time=evaluation_time,
                correlation_id=correlation,
            )
            await uow.thesis_versions.append(record)
            await uow.thesis_versions.link_evidence(record.id, evidence_ids)
            await uow.theses.update_current_version(
                thesis.id,
                expected_version=thesis.version,
                current_version_id=record.id,
                status=content.state.value,
            )
            await uow.commit()
            return ThesisWriteResult(
                thesis_id=thesis.id,
                thesis_version_id=record.id,
                version=version_number,
                created=True,
            )

    @staticmethod
    def _version_record(
        version: ThesisVersion,
        *,
        created_at: datetime,
        evaluation_time: datetime,
        correlation_id: UUID,
    ) -> ThesisVersionRecord:
        payload = thesis_content_payload(version.content)
        return ThesisVersionRecord(
            id=version.id,
            thesis_id=version.thesis_id,
            version=version.version,
            parent_version_id=version.parent_version_id,
            thesis_state=version.content.state.value,
            summary=version.content.long_term_summary,
            pillars_json=payload["pillars"],
            catalysts_json=payload["catalysts"],
            risks_json=payload["risks"],
            invalidation_conditions_json=payload["invalidation_conditions"],
            monitoring_conditions_json=payload["monitoring_conditions"],
            change_reason=version.content.change_reason.value,
            content_hash=version.content_hash,
            created_at=created_at,
            created_by="thesis_engine",
            correlation_id=correlation_id,
            causation_id=None,
            metadata_json={"as_of": evaluation_time.isoformat()},
        )


class SqlAlchemyThesisReader:
    """Read immutable Thesis versions without exposing ORM state to transport code."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def current_for_instrument(self, instrument_id: UUID) -> ThesisVersionRead | None:
        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            thesis = await uow.theses.get_by_instrument(instrument_id)
            if thesis is None or thesis.current_version_id is None:
                return None
            record = await uow.thesis_versions.get(thesis.current_version_id)
            if record is None:
                return None
            return await self._read_model(uow, thesis, record)

    async def as_of_for_instrument(
        self, instrument_id: UUID, *, as_of: datetime
    ) -> ThesisVersionRead | None:
        requested_time = UtcTimestamp(as_of).value
        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            thesis = await uow.theses.get_by_instrument(instrument_id)
            if thesis is None:
                return None
            record = await uow.thesis_versions.latest_as_of(thesis.id, as_of=requested_time)
            if record is None:
                return None
            return await self._read_model(uow, thesis, record)

    async def history_for_instrument(self, instrument_id: UUID) -> tuple[ThesisVersionRead, ...]:
        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            thesis = await uow.theses.get_by_instrument(instrument_id)
            if thesis is None:
                return ()
            records = await uow.thesis_versions.list_for_thesis(thesis.id)
            return tuple([await self._read_model(uow, thesis, record) for record in records])

    @staticmethod
    async def _read_model(
        uow: SqlAlchemyUnitOfWork,
        thesis: InvestmentThesisRecord,
        record: ThesisVersionRecord,
    ) -> ThesisVersionRead:
        evidence_ids = tuple(
            (
                await uow.session.scalars(
                    select(ThesisVersionEvidenceRecord.evidence_id)
                    .where(ThesisVersionEvidenceRecord.thesis_version_id == record.id)
                    .order_by(ThesisVersionEvidenceRecord.evidence_id)
                )
            ).all()
        )
        return ThesisVersionRead(
            instrument_id=thesis.instrument_id,
            thesis_id=thesis.id,
            version_id=record.id,
            version=record.version,
            parent_version_id=record.parent_version_id,
            state=record.thesis_state,
            summary=record.summary,
            pillars=record.pillars_json,
            catalysts=record.catalysts_json,
            risks=record.risks_json,
            invalidation_conditions=record.invalidation_conditions_json,
            monitoring_conditions=record.monitoring_conditions_json,
            change_reason=record.change_reason,
            evidence_ids=evidence_ids,
            created_at=record.created_at,
        )


class SqlAlchemyThesisInvalidationMonitor:
    """Evaluate explicit Thesis conditions and persist only a checked BROKEN proposal."""

    def __init__(self, writer: SqlAlchemyThesisWriter) -> None:
        self._writer = writer

    async def evaluate_and_write(
        self,
        *,
        instrument_id: UUID,
        current_content: ThesisContent,
        observations: tuple[MetricObservation, ...],
        as_of: datetime,
        correlation_id: UUID | None = None,
    ) -> ThesisInvalidationWriteResult:
        evaluation = evaluate_invalidation(current_content, observations)
        if evaluation.proposed_content is None:
            return ThesisInvalidationWriteResult(evaluation=evaluation, thesis_write=None)
        thesis_write = await self._writer.write(
            instrument_id=instrument_id,
            content=evaluation.proposed_content,
            as_of=as_of,
            correlation_id=correlation_id,
            expected_current_content_hash=thesis_content_hash(current_content),
        )
        return ThesisInvalidationWriteResult(evaluation=evaluation, thesis_write=thesis_write)
