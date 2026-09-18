from unittest.mock import AsyncMock

import pytest

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.infrastructure.persistence.locks import advisory_lock_key
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork


def test_advisory_lock_key_is_stable_and_namespaced() -> None:
    first = advisory_lock_key("task_run", "daily:2026-09-17")
    assert first == advisory_lock_key("task_run", "daily:2026-09-17")
    assert first != advisory_lock_key("other", "daily:2026-09-17")
    assert -(2**63) <= first < 2**63


def test_application_error_preserves_stable_code_and_details() -> None:
    error = ApplicationError(
        ApplicationErrorCode.OPTIMISTIC_CONCURRENCY_CONFLICT,
        "stale write",
        details={"expected_version": 3},
    )
    assert error.code is ApplicationErrorCode.OPTIMISTIC_CONCURRENCY_CONFLICT
    assert error.message == "stale write"
    assert error.details == {"expected_version": 3}


@pytest.mark.asyncio
async def test_unit_of_work_rolls_back_when_scope_exits_without_commit() -> None:
    session = AsyncMock()

    def session_factory() -> AsyncMock:
        return session

    async with SqlAlchemyUnitOfWork(session_factory) as uow:  # type: ignore[arg-type]
        assert uow.session is session

    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_unit_of_work_does_not_rollback_after_explicit_commit() -> None:
    session = AsyncMock()

    def session_factory() -> AsyncMock:
        return session

    async with SqlAlchemyUnitOfWork(session_factory) as uow:  # type: ignore[arg-type]
        await uow.commit()

    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()
    session.close.assert_awaited_once()
