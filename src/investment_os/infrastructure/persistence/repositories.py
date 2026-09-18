"""Typed repositories for PR-02 governed aggregates and immutable records."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    EventLogRecord,
    EvidenceRecord,
    InvestmentDecisionRecord,
    InvestmentPolicyRecord,
    InvestmentThesisRecord,
    OutboxEventRecord,
    PositionRecord,
    ResearchArtifactRecord,
    TaskRunRecord,
)


def _concurrency_conflict(entity: str, entity_id: UUID, expected_version: int) -> ApplicationError:
    return ApplicationError(
        ApplicationErrorCode.OPTIMISTIC_CONCURRENCY_CONFLICT,
        f"stale {entity} write rejected",
        details={"entity_id": str(entity_id), "expected_version": expected_version},
    )


class PositionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, record: PositionRecord) -> None:
        self._session.add(record)
        await self._session.flush()

    async def get(self, record_id: UUID) -> PositionRecord | None:
        return await self._session.get(PositionRecord, record_id)

    async def update_quantities(
        self,
        record_id: UUID,
        *,
        expected_version: int,
        core_quantity: Decimal,
        tactical_quantity: Decimal,
    ) -> PositionRecord:
        statement = (
            update(PositionRecord)
            .where(PositionRecord.id == record_id, PositionRecord.version == expected_version)
            .values(
                core_quantity=core_quantity,
                tactical_quantity=tactical_quantity,
                version=expected_version + 1,
            )
            .returning(PositionRecord)
        )
        updated = (await self._session.scalars(statement)).one_or_none()
        if updated is None:
            raise _concurrency_conflict("position", record_id, expected_version)
        return updated


class ThesisRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, record: InvestmentThesisRecord) -> None:
        self._session.add(record)
        await self._session.flush()

    async def get(self, record_id: UUID) -> InvestmentThesisRecord | None:
        return await self._session.get(InvestmentThesisRecord, record_id)

    async def update_current_version(
        self,
        record_id: UUID,
        *,
        expected_version: int,
        current_version_id: UUID,
        status: str,
    ) -> InvestmentThesisRecord:
        statement = (
            update(InvestmentThesisRecord)
            .where(
                InvestmentThesisRecord.id == record_id,
                InvestmentThesisRecord.version == expected_version,
            )
            .values(
                current_version_id=current_version_id,
                status=status,
                version=expected_version + 1,
            )
            .returning(InvestmentThesisRecord)
        )
        updated = (await self._session.scalars(statement)).one_or_none()
        if updated is None:
            raise _concurrency_conflict("investment_thesis", record_id, expected_version)
        return updated


class DecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, record_id: UUID) -> InvestmentDecisionRecord | None:
        return await self._session.get(InvestmentDecisionRecord, record_id)

    async def update_state(
        self,
        record_id: UUID,
        *,
        expected_version: int,
        state: str,
    ) -> InvestmentDecisionRecord:
        statement = (
            update(InvestmentDecisionRecord)
            .where(
                InvestmentDecisionRecord.id == record_id,
                InvestmentDecisionRecord.version == expected_version,
            )
            .values(state=state, version=expected_version + 1)
            .returning(InvestmentDecisionRecord)
        )
        updated = (await self._session.scalars(statement)).one_or_none()
        if updated is None:
            raise _concurrency_conflict("investment_decision", record_id, expected_version)
        return updated


class PolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, record: InvestmentPolicyRecord) -> None:
        self._session.add(record)
        await self._session.flush()

    async def get(self, record_id: UUID) -> InvestmentPolicyRecord | None:
        return await self._session.get(InvestmentPolicyRecord, record_id)

    async def activate_version(
        self,
        record_id: UUID,
        *,
        expected_version: int,
        current_version_id: UUID,
    ) -> InvestmentPolicyRecord:
        statement = (
            update(InvestmentPolicyRecord)
            .where(
                InvestmentPolicyRecord.id == record_id,
                InvestmentPolicyRecord.version == expected_version,
            )
            .values(
                current_version_id=current_version_id,
                status="ACTIVE",
                version=expected_version + 1,
            )
            .returning(InvestmentPolicyRecord)
        )
        updated = (await self._session.scalars(statement)).one_or_none()
        if updated is None:
            raise _concurrency_conflict("investment_policy", record_id, expected_version)
        return updated


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, record: AuditLogRecord) -> None:
        self._session.add(record)
        await self._session.flush()


class EvidenceRepository:
    """Append-only Evidence persistence with content-addressed deduplication."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_source_content(
        self, *, source_name: str, source_locator: str, content_hash: str
    ) -> EvidenceRecord | None:
        statement = select(EvidenceRecord).where(
            EvidenceRecord.source_name == source_name,
            EvidenceRecord.source_locator == source_locator,
            EvidenceRecord.content_hash == content_hash,
        )
        return (await self._session.scalars(statement)).one_or_none()

    async def append(self, record: EvidenceRecord) -> None:
        self._session.add(record)
        await self._session.flush()


class ResearchArtifactRepository:
    """Immutable raw-to-normalized lineage records for external research input."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, record: ResearchArtifactRecord) -> None:
        self._session.add(record)
        await self._session.flush()


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, record: EventLogRecord) -> None:
        self._session.add(record)
        await self._session.flush()


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, record: OutboxEventRecord) -> None:
        self._session.add(record)
        await self._session.flush()

    async def unpublished(self, *, limit: int = 100) -> list[OutboxEventRecord]:
        statement = (
            select(OutboxEventRecord)
            .where(OutboxEventRecord.published_at.is_(None))
            .order_by(OutboxEventRecord.created_at, OutboxEventRecord.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list((await self._session.scalars(statement)).all())

    async def mark_published(self, record_id: UUID, *, published_at: datetime) -> None:
        record = await self._session.get(OutboxEventRecord, record_id)
        if record is None:
            raise LookupError(f"outbox event {record_id} does not exist")
        record.published_at = published_at
        record.attempts += 1
        record.last_error = None
        await self._session.flush()

    async def record_failure(self, record_id: UUID, *, error_code: str) -> None:
        record = await self._session.get(OutboxEventRecord, record_id)
        if record is None:
            raise LookupError(f"outbox event {record_id} does not exist")
        record.attempts += 1
        record.last_error = error_code
        await self._session.flush()


class TaskRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_idempotency_key(self, key: str) -> TaskRunRecord | None:
        statement = select(TaskRunRecord).where(TaskRunRecord.idempotency_key == key)
        return (await self._session.scalars(statement)).one_or_none()

    async def start_or_retry(
        self,
        *,
        task_name: str,
        scheduled_for: datetime,
        idempotency_key: str,
        input_hash: str,
        started_at: datetime,
        correlation_id: UUID,
    ) -> TaskRunRecord:
        record = await self.get_by_idempotency_key(idempotency_key)
        if record is None:
            record = TaskRunRecord(
                task_name=task_name,
                scheduled_for=scheduled_for,
                status="RUNNING",
                attempt=1,
                idempotency_key=idempotency_key,
                input_hash=input_hash,
                started_at=started_at,
                correlation_id=correlation_id,
                created_by="reliable_job_executor",
                causation_id=None,
                metadata_json={},
            )
            self._session.add(record)
        else:
            record.status = "RUNNING"
            record.attempt += 1
            record.input_hash = input_hash
            record.started_at = started_at
            record.finished_at = None
            record.error_json = None
            record.correlation_id = correlation_id
        await self._session.flush()
        return record

    async def succeed(self, record: TaskRunRecord, *, finished_at: datetime) -> None:
        record.status = "SUCCEEDED"
        record.finished_at = finished_at
        record.error_json = None
        await self._session.flush()

    async def fail(
        self,
        record: TaskRunRecord,
        *,
        finished_at: datetime,
        error_code: str,
        error_type: str,
    ) -> None:
        record.status = "FAILED"
        record.finished_at = finished_at
        record.error_json = {"code": error_code, "type": error_type}
        await self._session.flush()
