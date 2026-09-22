from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from investment_os.application.secrets import SecretStoreUnavailable
from investment_os.infrastructure.secrets import EncryptedFileSecretStore


async def test_encrypted_file_store_round_trips_without_writing_plaintext(tmp_path) -> None:
    store_path = tmp_path / "credentials.json"
    reference = uuid4()
    store = EncryptedFileSecretStore(store_path, Fernet.generate_key().decode("ascii"))

    await store.put(reference, "synthetic-credential-value")

    assert await store.get(reference) == "synthetic-credential-value"
    assert "synthetic-credential-value" not in store_path.read_text(encoding="utf-8")
    await store.delete(reference)
    assert await store.get(reference) is None


async def test_encrypted_file_store_fails_closed_for_a_missing_or_invalid_key(tmp_path) -> None:
    with pytest.raises(SecretStoreUnavailable):
        EncryptedFileSecretStore(tmp_path / "credentials.json", "")

    with pytest.raises(SecretStoreUnavailable):
        EncryptedFileSecretStore(tmp_path / "credentials.json", "not-a-fernet-key")
