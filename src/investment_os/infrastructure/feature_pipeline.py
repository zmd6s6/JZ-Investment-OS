"""Persistence boundary for deterministic, provenance-preserving feature snapshots."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.evidence import FeatureSnapshot
from investment_os.infrastructure.persistence.models import FeatureSnapshotRecord
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork


@dataclass(frozen=True, slots=True)
class FeatureSnapshotWriteResult:
    snapshot_id: UUID


class SqlAlchemyFeatureSnapshotWriter:
    """Append a deterministic feature output with its input hash and correlation id."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        now: Callable[[], datetime],
    ) -> None:
        self._session_factory = session_factory
        self._now = now

    async def persist(
        self, snapshot: FeatureSnapshot, *, correlation_id: UUID | None = None
    ) -> FeatureSnapshotWriteResult:
        correlation = correlation_id or uuid4()
        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            record = FeatureSnapshotRecord(
                instrument_id=snapshot.instrument_id,
                as_of=snapshot.as_of.value,
                feature_set_version=snapshot.feature_set_version,
                values_json=dict(snapshot.values),
                input_hash=snapshot.input_hash,
                created_by="feature_pipeline",
                correlation_id=correlation,
                causation_id=None,
                metadata_json={"computed_at": self._now().isoformat()},
            )
            await uow.feature_snapshots.append(record)
            await uow.commit()
            return FeatureSnapshotWriteResult(snapshot_id=record.id)
