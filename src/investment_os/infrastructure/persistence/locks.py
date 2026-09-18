"""Transaction-scoped PostgreSQL advisory locks for logical jobs."""

from hashlib import sha256

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def advisory_lock_key(namespace: str, logical_key: str) -> int:
    """Derive a stable signed 64-bit key without Python's randomized hash()."""

    digest = sha256(f"{namespace}:{logical_key}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


async def try_transaction_advisory_lock(
    session: AsyncSession, *, namespace: str, logical_key: str
) -> bool:
    key = advisory_lock_key(namespace, logical_key)
    result = await session.execute(
        text("SELECT pg_try_advisory_xact_lock(:lock_key)"), {"lock_key": key}
    )
    return bool(result.scalar_one())
