from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from investment_os.application.provider_settings import ProviderSettingsService
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    EventLogRecord,
    ModelProviderProfileRecord,
    OutboxEventRecord,
)
from investment_os.infrastructure.provider_settings import SqlAlchemyProviderSettingsStore


class MemorySecretStore:
    def __init__(self) -> None:
        self.values: dict[UUID, str] = {}

    async def put(self, credential_ref: UUID, value: str) -> None:
        self.values[credential_ref] = value

    async def get(self, credential_ref: UUID) -> str | None:
        return self.values.get(credential_ref)

    async def delete(self, credential_ref: UUID) -> None:
        self.values.pop(credential_ref, None)


async def test_provider_profile_writes_secret_free_event_outbox_and_audit_records(
    database_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(database_engine, expire_on_commit=False, class_=AsyncSession)
    secret_store = MemorySecretStore()
    service = ProviderSettingsService(
        SqlAlchemyProviderSettingsStore(factory),
        secret_store,  # type: ignore[arg-type]
    )

    profile = await service.save_model_profile(
        profile_id=None,
        name="primary-model",
        provider_type="OPENAI_COMPATIBLE",
        base_url="https://models.example.invalid/v1",
        model_name="synthetic-model",
        timeout_seconds=30,
        max_tokens=1024,
        enabled=True,
        credential="synthetic-credential",
    )
    result = await service.test_model_profile(profile.id)

    async with factory() as session:
        record = await session.get(ModelProviderProfileRecord, profile.id)
        events = list((await session.scalars(select(EventLogRecord))).all())
        outbox = list((await session.scalars(select(OutboxEventRecord))).all())
        audits = list((await session.scalars(select(AuditLogRecord))).all())

    assert record is not None
    assert record.credential_ref is not None
    assert secret_store.values[record.credential_ref] == "synthetic-credential"
    assert result.status == "CONFIGURATION_VALID"
    assert len(events) == len(outbox) == len(audits) == 2
    persisted_history = str(
        [
            *(event.payload_json for event in events),
            *(item.payload_json for item in outbox),
            *(audit.metadata_json for audit in audits),
        ]
    )
    assert "synthetic-credential" not in persisted_history
    assert "credential_ref" not in persisted_history
