"""SQLAlchemy adapter for P2 settings, provider profiles, and secret-free audit history."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.provider_settings import (
    DataProviderProfile,
    ModelProviderProfile,
    ProviderSyncHistoryEntry,
    ProviderTestHistoryEntry,
    ProviderTestResult,
    ProviderTestStatus,
    RoleModelAssignment,
    SystemSettings,
)
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    DataProviderProfileRecord,
    EventLogRecord,
    ModelProviderProfileRecord,
    OutboxEventRecord,
    RoleModelAssignmentRecord,
    SystemSettingsRecord,
)

_PROVIDER_TEST_STATUSES: frozenset[ProviderTestStatus] = frozenset(
    {
        "CONFIGURATION_VALID",
        "CREDENTIAL_MISSING",
        "SECRET_STORE_UNAVAILABLE",
        "CONNECTION_SUCCEEDED",
        "CONNECTION_FAILED",
        "UNSUPPORTED_PROVIDER",
    }
)

SYSTEM_SETTINGS_ID = UUID("00000000-0000-0000-0000-000000000002")


def _provider_test_history_entry(
    *, occurred_at: datetime, payload: Mapping[str, object]
) -> ProviderTestHistoryEntry:
    status = payload.get("result")
    latency_ms = payload.get("latency_ms")
    if not isinstance(status, str) or status not in _PROVIDER_TEST_STATUSES:
        raise ValueError("provider test audit record has invalid status")
    if latency_ms is not None and (not isinstance(latency_ms, int) or latency_ms < 0):
        raise ValueError("provider test audit record has invalid latency")
    return ProviderTestHistoryEntry(
        status=status,
        occurred_at=occurred_at,
        latency_ms=latency_ms,
    )


class SqlAlchemyProviderSettingsStore:
    """Transactional persistence of configuration metadata, never credential material."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_system_settings(self) -> SystemSettings:
        async with self._session_factory() as session:
            record = await session.get(SystemSettingsRecord, SYSTEM_SETTINGS_ID)
        if record is None:
            return SystemSettings(market_timezone="Asia/Shanghai", market_scopes=())
        return self._system_settings(record)

    async def save_system_settings(self, settings: SystemSettings) -> SystemSettings:
        async with self._session_factory() as session:
            record = await session.get(
                SystemSettingsRecord, SYSTEM_SETTINGS_ID, with_for_update=True
            )
            before = self._system_payload(record) if record else None
            if record is None:
                record = SystemSettingsRecord(
                    id=SYSTEM_SETTINGS_ID,
                    market_timezone=settings.market_timezone,
                    market_scopes_json=list(settings.market_scopes),
                    auto_trade=False,
                )
                session.add(record)
                operation = "CREATE"
            else:
                record.market_timezone = settings.market_timezone
                record.market_scopes_json = list(settings.market_scopes)
                record.updated_at = datetime.now(UTC)
                operation = "UPDATE"
            await self._record_change(
                session,
                operation=operation,
                aggregate_type="SystemSettings",
                aggregate_id=SYSTEM_SETTINGS_ID,
                payload=self._system_payload(record),
                before=before,
            )
            await session.commit()
        return settings

    async def list_model_profiles(self) -> list[ModelProviderProfile]:
        async with self._session_factory() as session:
            records = list(
                (
                    await session.scalars(
                        select(ModelProviderProfileRecord).order_by(
                            ModelProviderProfileRecord.name, ModelProviderProfileRecord.id
                        )
                    )
                ).all()
            )
        return [self._model_profile(record) for record in records]

    async def get_model_profile(self, profile_id: UUID) -> ModelProviderProfile | None:
        async with self._session_factory() as session:
            record = await session.get(ModelProviderProfileRecord, profile_id)
        return self._model_profile(record) if record else None

    async def save_model_profile(self, profile: ModelProviderProfile) -> ModelProviderProfile:
        async with self._session_factory() as session:
            record = await session.get(ModelProviderProfileRecord, profile.id, with_for_update=True)
            before = self._model_payload(record) if record else None
            if record is None:
                record = ModelProviderProfileRecord(id=profile.id, **self._model_values(profile))
                session.add(record)
                operation = "CREATE"
            else:
                for field, value in self._model_values(profile).items():
                    setattr(record, field, value)
                record.updated_at = datetime.now(UTC)
                operation = "UPDATE"
            await self._record_change(
                session,
                operation=operation,
                aggregate_type="ModelProviderProfile",
                aggregate_id=profile.id,
                payload=self._model_payload(record),
                before=before,
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise ValueError("model_provider_name_conflict") from exc
        return profile

    async def delete_model_profile(self, profile_id: UUID) -> bool:
        async with self._session_factory() as session:
            record = await session.get(ModelProviderProfileRecord, profile_id, with_for_update=True)
            if record is None:
                return False
            payload = self._model_payload(record)
            await session.delete(record)
            await self._record_change(
                session,
                operation="DELETE",
                aggregate_type="ModelProviderProfile",
                aggregate_id=profile_id,
                payload={"deleted": True},
                before=payload,
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise ValueError("model_provider_is_assigned") from exc
        return True

    async def list_data_profiles(self) -> list[DataProviderProfile]:
        async with self._session_factory() as session:
            records = list(
                (
                    await session.scalars(
                        select(DataProviderProfileRecord).order_by(
                            DataProviderProfileRecord.name, DataProviderProfileRecord.id
                        )
                    )
                ).all()
            )
        return [self._data_profile(record) for record in records]

    async def get_data_profile(self, profile_id: UUID) -> DataProviderProfile | None:
        async with self._session_factory() as session:
            record = await session.get(DataProviderProfileRecord, profile_id)
        return self._data_profile(record) if record else None

    async def save_data_profile(self, profile: DataProviderProfile) -> DataProviderProfile:
        async with self._session_factory() as session:
            record = await session.get(DataProviderProfileRecord, profile.id, with_for_update=True)
            before = self._data_payload(record) if record else None
            if record is None:
                record = DataProviderProfileRecord(id=profile.id, **self._data_values(profile))
                session.add(record)
                operation = "CREATE"
            else:
                for field, value in self._data_values(profile).items():
                    setattr(record, field, value)
                record.updated_at = datetime.now(UTC)
                operation = "UPDATE"
            await self._record_change(
                session,
                operation=operation,
                aggregate_type="DataProviderProfile",
                aggregate_id=profile.id,
                payload=self._data_payload(record),
                before=before,
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise ValueError("data_provider_name_conflict") from exc
        return profile

    async def delete_data_profile(self, profile_id: UUID) -> bool:
        async with self._session_factory() as session:
            record = await session.get(DataProviderProfileRecord, profile_id, with_for_update=True)
            if record is None:
                return False
            payload = self._data_payload(record)
            await session.delete(record)
            await self._record_change(
                session,
                operation="DELETE",
                aggregate_type="DataProviderProfile",
                aggregate_id=profile_id,
                payload={"deleted": True},
                before=payload,
            )
            await session.commit()
        return True

    async def list_role_assignments(self) -> list[RoleModelAssignment]:
        async with self._session_factory() as session:
            records = list(
                (
                    await session.scalars(
                        select(RoleModelAssignmentRecord).order_by(RoleModelAssignmentRecord.role)
                    )
                ).all()
            )
        return [
            RoleModelAssignment(
                role=record.role, model_provider_profile_id=record.model_provider_profile_id
            )
            for record in records
        ]

    async def save_role_assignment(self, assignment: RoleModelAssignment) -> RoleModelAssignment:
        async with self._session_factory() as session:
            record = await session.scalar(
                select(RoleModelAssignmentRecord)
                .where(RoleModelAssignmentRecord.role == assignment.role)
                .with_for_update()
            )
            before = self._assignment_payload(record) if record else None
            if record is None:
                record = RoleModelAssignmentRecord(
                    id=uuid4(),
                    role=assignment.role,
                    model_provider_profile_id=assignment.model_provider_profile_id,
                )
                session.add(record)
                operation = "CREATE"
            else:
                record.model_provider_profile_id = assignment.model_provider_profile_id
                record.updated_at = datetime.now(UTC)
                operation = "UPDATE"
            await self._record_change(
                session,
                operation=operation,
                aggregate_type="RoleModelAssignment",
                aggregate_id=record.id,
                payload=self._assignment_payload(record),
                before=before,
            )
            await session.commit()
        return assignment

    async def delete_role_assignment(self, role: str) -> bool:
        async with self._session_factory() as session:
            record = await session.scalar(
                select(RoleModelAssignmentRecord)
                .where(RoleModelAssignmentRecord.role == role)
                .with_for_update()
            )
            if record is None:
                return False
            payload = self._assignment_payload(record)
            await session.delete(record)
            await self._record_change(
                session,
                operation="DELETE",
                aggregate_type="RoleModelAssignment",
                aggregate_id=record.id,
                payload={"role": role, "deleted": True},
                before=payload,
            )
            await session.commit()
        return True

    async def record_provider_test(
        self,
        *,
        profile_id: UUID,
        provider_kind: Literal["MODEL", "DATA"],
        result: ProviderTestResult,
    ) -> None:
        async with self._session_factory() as session:
            await self._record_change(
                session,
                operation="TEST",
                aggregate_type=f"{provider_kind.title()}ProviderProfile",
                aggregate_id=profile_id,
                payload={
                    "operation": "CONNECTION_TEST",
                    "result": result.status,
                    "latency_ms": result.latency_ms,
                },
                before=None,
            )
            await session.commit()

    async def latest_provider_test(
        self, *, profile_id: UUID, provider_kind: Literal["MODEL", "DATA"]
    ) -> ProviderTestHistoryEntry | None:
        aggregate_type = f"{provider_kind.title()}ProviderProfile"
        async with self._session_factory() as session:
            records = list(
                (
                    await session.scalars(
                        select(EventLogRecord)
                        .where(
                            EventLogRecord.aggregate_type == aggregate_type,
                            EventLogRecord.aggregate_id == profile_id,
                            EventLogRecord.event_type == f"product_settings.{aggregate_type}.test",
                        )
                        .order_by(desc(EventLogRecord.occurred_at))
                        .limit(1)
                    )
                ).all()
            )
        if not records:
            return None
        return _provider_test_history_entry(
            occurred_at=records[0].occurred_at,
            payload=records[0].payload_json,
        )

    async def record_data_provider_sync(
        self, *, profile_id: UUID, artifact_count: int, latency_ms: int
    ) -> None:
        async with self._session_factory() as session:
            await self._record_change(
                session,
                operation="SYNC",
                aggregate_type="DataProviderProfile",
                aggregate_id=profile_id,
                payload={
                    "operation": "RESEARCH_FETCH",
                    "artifact_count": artifact_count,
                    "latency_ms": latency_ms,
                },
                before=None,
            )
            await session.commit()

    async def latest_data_provider_sync(
        self, *, profile_id: UUID
    ) -> ProviderSyncHistoryEntry | None:
        async with self._session_factory() as session:
            record = await session.scalar(
                select(EventLogRecord)
                .where(
                    EventLogRecord.aggregate_type == "DataProviderProfile",
                    EventLogRecord.aggregate_id == profile_id,
                    EventLogRecord.event_type == "product_settings.DataProviderProfile.sync",
                )
                .order_by(desc(EventLogRecord.occurred_at))
                .limit(1)
            )
        if record is None:
            return None
        artifact_count = record.payload_json.get("artifact_count")
        latency_ms = record.payload_json.get("latency_ms")
        if (
            not isinstance(artifact_count, int)
            or isinstance(artifact_count, bool)
            or artifact_count < 0
            or not isinstance(latency_ms, int)
            or isinstance(latency_ms, bool)
            or latency_ms < 0
        ):
            raise ValueError("provider sync audit record has invalid metrics")
        return ProviderSyncHistoryEntry(
            occurred_at=record.occurred_at,
            artifact_count=artifact_count,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _system_settings(record: SystemSettingsRecord) -> SystemSettings:
        return SystemSettings(
            market_timezone=record.market_timezone,
            market_scopes=tuple(record.market_scopes_json),
            auto_trade=False,
        )

    @staticmethod
    def _model_profile(record: ModelProviderProfileRecord) -> ModelProviderProfile:
        return ModelProviderProfile(
            id=record.id,
            name=record.name,
            provider_type=record.provider_type,
            base_url=record.base_url,
            model_name=record.model_name,
            credential_ref=record.credential_ref,
            timeout_seconds=record.timeout_seconds,
            max_tokens=record.max_tokens,
            enabled=record.enabled,
            pricing_version=record.pricing_version,
            pricing_currency=record.pricing_currency,
            input_token_price=record.input_token_price,
            output_token_price=record.output_token_price,
            pricing_effective_at=record.pricing_effective_at,
        )

    @staticmethod
    def _data_profile(record: DataProviderProfileRecord) -> DataProviderProfile:
        return DataProviderProfile(
            id=record.id,
            name=record.name,
            provider_type=record.provider_type,
            base_url=record.base_url,
            credential_ref=record.credential_ref,
            timeout_seconds=record.timeout_seconds,
            enabled=record.enabled,
            retention_days=record.retention_days,
        )

    @staticmethod
    def _model_values(profile: ModelProviderProfile) -> dict[str, object]:
        return {
            "name": profile.name,
            "provider_type": profile.provider_type,
            "base_url": profile.base_url,
            "model_name": profile.model_name,
            "credential_ref": profile.credential_ref,
            "timeout_seconds": profile.timeout_seconds,
            "max_tokens": profile.max_tokens,
            "enabled": profile.enabled,
            "pricing_version": profile.pricing_version,
            "pricing_currency": profile.pricing_currency,
            "input_token_price": profile.input_token_price,
            "output_token_price": profile.output_token_price,
            "pricing_effective_at": profile.pricing_effective_at,
        }

    @staticmethod
    def _data_values(profile: DataProviderProfile) -> dict[str, object]:
        return {
            "name": profile.name,
            "provider_type": profile.provider_type,
            "base_url": profile.base_url,
            "credential_ref": profile.credential_ref,
            "timeout_seconds": profile.timeout_seconds,
            "enabled": profile.enabled,
            "retention_days": profile.retention_days,
        }

    @staticmethod
    def _system_payload(record: SystemSettingsRecord) -> dict[str, object]:
        return {
            "market_timezone": record.market_timezone,
            "market_scopes": record.market_scopes_json,
            "auto_trade": False,
        }

    @staticmethod
    def _model_payload(record: ModelProviderProfileRecord) -> dict[str, object]:
        return {
            "name": record.name,
            "provider_type": record.provider_type,
            "base_url": record.base_url,
            "model_name": record.model_name,
            "credential_configured": record.credential_ref is not None,
            "timeout_seconds": record.timeout_seconds,
            "max_tokens": record.max_tokens,
            "enabled": record.enabled,
            "pricing_version": record.pricing_version,
            "pricing_currency": record.pricing_currency,
            "input_token_price": str(record.input_token_price)
            if record.input_token_price is not None
            else None,
            "output_token_price": str(record.output_token_price)
            if record.output_token_price is not None
            else None,
            "pricing_effective_at": record.pricing_effective_at.isoformat()
            if record.pricing_effective_at
            else None,
        }

    @staticmethod
    def _data_payload(record: DataProviderProfileRecord) -> dict[str, object]:
        return {
            "name": record.name,
            "provider_type": record.provider_type,
            "base_url": record.base_url,
            "credential_configured": record.credential_ref is not None,
            "timeout_seconds": record.timeout_seconds,
            "enabled": record.enabled,
            "retention_days": record.retention_days,
        }

    @staticmethod
    def _assignment_payload(record: RoleModelAssignmentRecord) -> dict[str, object]:
        return {
            "role": record.role,
            "model_provider_profile_id": str(record.model_provider_profile_id),
        }

    @staticmethod
    async def _record_change(
        session: AsyncSession,
        *,
        operation: str,
        aggregate_type: str,
        aggregate_id: UUID,
        payload: dict[str, object],
        before: dict[str, object] | None,
    ) -> None:
        occurred_at = datetime.now(UTC)
        correlation_id = uuid4()
        event_type = f"product_settings.{aggregate_type}.{operation.lower()}"
        event = EventLogRecord(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload_json=payload,
            occurred_at=occurred_at,
            correlation_id=correlation_id,
            causation_id=None,
            schema_version="1.0",
            metadata_json={},
            created_by="product_settings",
        )
        session.add(event)
        await session.flush()
        session.add(
            OutboxEventRecord(
                event_id=event.id,
                topic=event_type,
                payload_json=payload,
                published_at=None,
                attempts=0,
                last_error=None,
                correlation_id=correlation_id,
                causation_id=event.id,
                schema_version="1.0",
                metadata_json={},
                created_by="product_settings",
            )
        )
        session.add(
            AuditLogRecord(
                id=uuid4(),
                actor_type="SYSTEM",
                actor_id="product_settings",
                operation=operation,
                entity_type=aggregate_type,
                entity_id=aggregate_id,
                before_hash=SqlAlchemyProviderSettingsStore._hash_payload(before),
                after_hash=SqlAlchemyProviderSettingsStore._hash_payload(payload),
                ip_or_runtime_ref="api",
                occurred_at=occurred_at,
                correlation_id=correlation_id,
                causation_id=event.id,
                schema_version="1.0",
                metadata_json={},
                created_by="product_settings",
            )
        )

    @staticmethod
    def _hash_payload(payload: dict[str, object] | None) -> str | None:
        if payload is None:
            return None
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return sha256(encoded).hexdigest()
