"""PostgreSQL implementation of fail-closed, atomically reserved LLM budgets."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.llm_budget import (
    LLMBudgetPolicy,
    LLMBudgetReservation,
    LLMBudgetUsage,
    ModelPricing,
)
from investment_os.infrastructure.persistence.models import (
    LLMBudgetDailyLedgerRecord,
    LLMBudgetPolicyRecord,
    LLMBudgetReservationRecord,
    LLMBudgetTaskLedgerRecord,
    LLMUsageRecord,
)

_POLICY_ID = UUID("00000000-0000-0000-0000-000000000014")


class SqlAlchemyLLMBudgetStore:
    """Rows are locked before every capacity decision, preventing concurrent overspend."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_policy(self) -> LLMBudgetPolicy | None:
        async with self._session_factory() as session:
            record = await session.get(LLMBudgetPolicyRecord, _POLICY_ID)
        return self._policy(record) if record else None

    async def save_policy(self, policy: LLMBudgetPolicy) -> LLMBudgetPolicy:
        async with self._session_factory() as session:
            record = await session.get(LLMBudgetPolicyRecord, _POLICY_ID, with_for_update=True)
            values = self._policy_values(policy)
            if record is None:
                session.add(LLMBudgetPolicyRecord(id=_POLICY_ID, **values))
            else:
                for field, value in values.items():
                    setattr(record, field, value)
            await session.commit()
        return policy

    async def reserve(
        self,
        *,
        task_id: UUID,
        profile_id: UUID,
        window_date: date,
        pricing: ModelPricing,
        input_tokens: int,
        output_tokens: int,
        cost: Decimal,
        policy: LLMBudgetPolicy,
    ) -> LLMBudgetReservation | None:
        total_tokens = input_tokens + output_tokens
        async with self._session_factory() as session:
            async with session.begin():
                # Serialize first-ledger creation as well as later row updates.  The daily
                # lock is deliberately wider than a task lock: a daily hard cap is shared.
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                    {"key": f"llm-budget-daily-{window_date.isoformat()}"},
                )
                daily = await session.get(
                    LLMBudgetDailyLedgerRecord, window_date, with_for_update=True
                )
                if daily is None:
                    daily = LLMBudgetDailyLedgerRecord(window_date=window_date)
                    session.add(daily)
                    await session.flush()
                    daily = await session.get(
                        LLMBudgetDailyLedgerRecord, window_date, with_for_update=True
                    )
                if daily is None:
                    raise RuntimeError("LLM daily budget ledger is unavailable")
                task = await session.get(LLMBudgetTaskLedgerRecord, task_id, with_for_update=True)
                if task is None:
                    task = LLMBudgetTaskLedgerRecord(task_id=task_id)
                    session.add(task)
                    await session.flush()
                    task = await session.get(
                        LLMBudgetTaskLedgerRecord, task_id, with_for_update=True
                    )
                if task is None:
                    raise RuntimeError("LLM task budget ledger is unavailable")
                if (
                    daily.consumed_tokens + daily.reserved_tokens + total_tokens
                    > policy.daily_token_limit
                    or daily.consumed_cost + daily.reserved_cost + cost > policy.daily_cost_limit
                    or task.consumed_tokens + task.reserved_tokens + total_tokens
                    > policy.task_token_limit
                    or task.consumed_cost + task.reserved_cost + cost > policy.task_cost_limit
                ):
                    return None
                daily.reserved_tokens += total_tokens
                daily.reserved_cost += cost
                task.reserved_tokens += total_tokens
                task.reserved_cost += cost
                reservation = LLMBudgetReservationRecord(
                    id=uuid4(),
                    task_id=task_id,
                    profile_id=profile_id,
                    window_date=window_date,
                    pricing_version=pricing.version,
                    currency=pricing.currency,
                    input_token_price=pricing.input_token_price,
                    output_token_price=pricing.output_token_price,
                    reserved_input_tokens=input_tokens,
                    reserved_output_tokens=output_tokens,
                    reserved_cost=cost,
                    status="RESERVED",
                )
                session.add(reservation)
            return self._reservation(reservation)

    async def reconcile(
        self,
        reservation: LLMBudgetReservation,
        *,
        input_tokens: int,
        output_tokens: int,
        cost: Decimal,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            record = await session.get(
                LLMBudgetReservationRecord, reservation.id, with_for_update=True
            )
            if record is None or record.status != "RESERVED":
                raise RuntimeError("LLM budget reservation is unavailable")
            daily = await session.get(
                LLMBudgetDailyLedgerRecord, record.window_date, with_for_update=True
            )
            task = await session.get(
                LLMBudgetTaskLedgerRecord, record.task_id, with_for_update=True
            )
            if daily is None or task is None:
                raise RuntimeError("LLM budget ledger is unavailable")
            reserved_tokens = record.reserved_input_tokens + record.reserved_output_tokens
            actual_tokens = input_tokens + output_tokens
            if actual_tokens > reserved_tokens or cost > record.reserved_cost:
                raise RuntimeError("LLM usage exceeds its reservation")
            daily.reserved_tokens -= reserved_tokens
            daily.reserved_cost -= record.reserved_cost
            daily.consumed_tokens += actual_tokens
            daily.consumed_cost += cost
            task.reserved_tokens -= reserved_tokens
            task.reserved_cost -= record.reserved_cost
            task.consumed_tokens += actual_tokens
            task.consumed_cost += cost
            record.status = "RECONCILED"
            session.add(
                LLMUsageRecord(
                    reservation_id=record.id,
                    task_id=record.task_id,
                    profile_id=record.profile_id,
                    window_date=record.window_date,
                    pricing_version=record.pricing_version,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_cost=cost,
                )
            )

    async def usage(self, *, window_date: date, policy: LLMBudgetPolicy) -> LLMBudgetUsage:
        async with self._session_factory() as session:
            record = await session.get(LLMBudgetDailyLedgerRecord, window_date)
        consumed_tokens = record.consumed_tokens if record else 0
        consumed_cost = record.consumed_cost if record else Decimal("0")
        reserved_tokens = record.reserved_tokens if record else 0
        reserved_cost = record.reserved_cost if record else Decimal("0")
        return LLMBudgetUsage(
            window_date,
            consumed_tokens,
            0,
            consumed_cost,
            max(0, policy.daily_token_limit - consumed_tokens - reserved_tokens),
            max(Decimal("0"), policy.daily_cost_limit - consumed_cost - reserved_cost),
            reserved_tokens,
            reserved_cost,
        )

    @staticmethod
    def _policy(record: LLMBudgetPolicyRecord) -> LLMBudgetPolicy:
        return LLMBudgetPolicy(
            record.version,
            record.currency,
            record.task_token_limit,
            record.daily_token_limit,
            record.task_cost_limit,
            record.daily_cost_limit,
        )

    @staticmethod
    def _policy_values(policy: LLMBudgetPolicy) -> dict[str, object]:
        return {
            "version": policy.version,
            "currency": policy.currency,
            "task_token_limit": policy.task_token_limit,
            "daily_token_limit": policy.daily_token_limit,
            "task_cost_limit": policy.task_cost_limit,
            "daily_cost_limit": policy.daily_cost_limit,
        }

    @staticmethod
    def _reservation(record: LLMBudgetReservationRecord) -> LLMBudgetReservation:
        return LLMBudgetReservation(
            record.id,
            record.task_id,
            record.profile_id,
            record.window_date,
            ModelPricing(
                record.pricing_version,
                record.currency,
                record.input_token_price,
                record.output_token_price,
            ),
            record.reserved_input_tokens,
            record.reserved_output_tokens,
            record.reserved_cost,
        )
