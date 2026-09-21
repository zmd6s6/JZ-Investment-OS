"""Application boundary for provider credentials that must never enter configuration records."""

from typing import Protocol
from uuid import UUID


class SecretStoreUnavailable(RuntimeError):
    """The configured store cannot safely read or write credentials."""


class SecretStore(Protocol):
    """Keep credential material out of API DTOs and database configuration records."""

    async def put(self, credential_ref: UUID, value: str) -> None: ...

    async def get(self, credential_ref: UUID) -> str | None: ...

    async def delete(self, credential_ref: UUID) -> None: ...


class UnavailableSecretStore:
    """Fail closed when deployment has not supplied a usable encryption key."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def put(self, credential_ref: UUID, value: str) -> None:
        raise SecretStoreUnavailable(self._reason)

    async def get(self, credential_ref: UUID) -> str | None:
        raise SecretStoreUnavailable(self._reason)

    async def delete(self, credential_ref: UUID) -> None:
        raise SecretStoreUnavailable(self._reason)
