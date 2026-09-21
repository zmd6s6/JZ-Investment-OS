"""SQLAlchemy adapter for P2 settings, provider profiles, and secret-free audit history."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.provider_settings import (
    DataProviderProfile,
    ModelProviderProfile,
    ProviderTestResult,
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

SYSTEM_SETTINGS_ID = UUID("00000000-0000-0000-0000-000000000002")


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
                payload={"result": result.status},
                before=None,
            )
            await session.commit()

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
