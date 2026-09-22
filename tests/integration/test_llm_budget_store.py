import asyncio
from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from investment_os.application.llm_budget import LLMBudgetPolicy, ModelPricing
from investment_os.infrastructure.llm_budget import SqlAlchemyLLMBudgetStore


def _policy(*, task_tokens: int = 100, daily_tokens: int = 100) -> LLMBudgetPolicy:
    return LLMBudgetPolicy(
        "TEST_DEFAULT", "USD", task_tokens, daily_tokens, Decimal("100"), Decimal("100")
    )


def _pricing() -> ModelPricing:
    return ModelPricing("TEST_PRICE", "USD", Decimal("0.01"), Decimal("0.02"))


async def test_daily_reservations_are_atomic_across_concurrent_store_calls(
    database_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(database_engine, expire_on_commit=False, class_=AsyncSession)
    store = SqlAlchemyLLMBudgetStore(factory)
    policy = _policy(daily_tokens=15)
    await store.save_policy(policy)
    window = date(2026, 9, 22)

    async def reserve() -> object:
        return await store.reserve(
            task_id=uuid4(),
            profile_id=uuid4(),
            window_date=window,
            pricing=_pricing(),
            input_tokens=5,
            output_tokens=5,
            cost=Decimal("0.15"),
            policy=policy,
        )

    first, second = await asyncio.gather(reserve(), reserve())
    assert sum(item is not None for item in (first, second)) == 1
    usage = await SqlAlchemyLLMBudgetStore(factory).usage(window_date=window, policy=policy)
    assert usage.reserved_tokens == 10
    assert usage.remaining_tokens == 5


async def test_task_limit_and_utc_daily_window_survive_store_recreation(
    database_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(database_engine, expire_on_commit=False, class_=AsyncSession)
    policy = _policy(task_tokens=10, daily_tokens=100)
    store = SqlAlchemyLLMBudgetStore(factory)
    await store.save_policy(policy)
    task_id = uuid4()
    first = await store.reserve(
        task_id=task_id,
        profile_id=uuid4(),
        window_date=date(2026, 9, 22),
        pricing=_pricing(),
        input_tokens=5,
        output_tokens=5,
        cost=Decimal("0.15"),
        policy=policy,
    )
    assert first is not None
    assert (
        await SqlAlchemyLLMBudgetStore(factory).reserve(
            task_id=task_id,
            profile_id=uuid4(),
            window_date=date(2026, 9, 23),
            pricing=_pricing(),
            input_tokens=1,
            output_tokens=1,
            cost=Decimal("0.03"),
            policy=policy,
        )
        is None
    )
    next_day = await SqlAlchemyLLMBudgetStore(factory).usage(
        window_date=date(2026, 9, 23), policy=policy
    )
    assert next_day.remaining_tokens == policy.daily_token_limit
