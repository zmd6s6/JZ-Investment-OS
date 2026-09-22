"""Local authenticated-encryption implementation of the SecretStore port."""

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

from investment_os.application.secrets import SecretStoreUnavailable


class EncryptedFileSecretStore:
    """Store only authenticated ciphertext in a local runtime file."""

    def __init__(self, path: Path, key: str) -> None:
        if not key:
            raise SecretStoreUnavailable("secret store key is not configured")
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (UnicodeEncodeError, ValueError) as exc:
            raise SecretStoreUnavailable("secret store key is invalid") from exc
        self._path = path
        self._lock = asyncio.Lock()

    async def put(self, credential_ref: UUID, value: str) -> None:
        if not value.strip():
            raise ValueError("credential value must not be blank")
        async with self._lock:
            values = await asyncio.to_thread(self._read)
            values[str(credential_ref)] = self._fernet.encrypt(value.encode("utf-8")).decode(
                "ascii"
            )
            await asyncio.to_thread(self._write, values)

    async def get(self, credential_ref: UUID) -> str | None:
        async with self._lock:
            token = (await asyncio.to_thread(self._read)).get(str(credential_ref))
        if token is None:
            return None
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise SecretStoreUnavailable("stored credential cannot be decrypted") from exc

    async def delete(self, credential_ref: UUID) -> None:
        async with self._lock:
            values = await asyncio.to_thread(self._read)
            if values.pop(str(credential_ref), None) is not None:
                await asyncio.to_thread(self._write, values)

    def _read(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SecretStoreUnavailable("secret store file cannot be read") from exc
        if not isinstance(raw, dict) or not all(
            isinstance(reference, str) and isinstance(token, str)
            for reference, token in raw.items()
        ):
            raise SecretStoreUnavailable("secret store file has an invalid schema")
        return raw

    def _write(self, values: dict[str, str]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self._path.with_name(f"{self._path.name}.tmp")
            temporary_path.write_text(
                json.dumps(values, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary_path, self._path)
            self._path.chmod(0o600)
        except OSError as exc:
            raise SecretStoreUnavailable("secret store file cannot be written") from exc
