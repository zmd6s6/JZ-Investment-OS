"""Explicit async Unit of Work for atomic database and outbox writes."""

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.infrastructure.persistence.repositories import (
    AuditRepository,
    DecisionRepository,
    EventRepository,
    OutboxRepository,
    PolicyRepository,
    PositionRepository,
    TaskRunRepository,
    ThesisRepository,
)


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session = session_factory()
        self.positions = PositionRepository(self.session)
        self.theses = ThesisRepository(self.session)
        self.decisions = DecisionRepository(self.session)
        self.policies = PolicyRepository(self.session)
        self.audit = AuditRepository(self.session)
        self.events = EventRepository(self.session)
        self.outbox = OutboxRepository(self.session)
        self.task_runs = TaskRunRepository(self.session)
        self._completed = False

    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if not self._completed:
            await self.session.rollback()
        await self.session.close()

    async def commit(self) -> None:
        await self.session.commit()
        self._completed = True

    async def rollback(self) -> None:
        await self.session.rollback()
        self._completed = True
