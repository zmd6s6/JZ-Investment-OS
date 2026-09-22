from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from investment_os.application.llm_budget import (
    LLMBudgetPolicy,
    LLMBudgetReservation,
    LLMBudgetService,
    LLMBudgetUsage,
    ModelPricing,
)
from investment_os.application.llm_gateway import LLMGatewayFailure, LLMGatewayRequest
from investment_os.application.provider_settings import ModelProviderProfile
from investment_os.domain.agent import AgentRole


class MemoryBudgetPort:
    def __init__(self, policy: LLMBudgetPolicy | None) -> None:
        self.policy = policy
        self.reservations: list[LLMBudgetReservation] = []

    async def get_policy(self) -> LLMBudgetPolicy | None:
        return self.policy

    async def save_policy(self, policy: LLMBudgetPolicy) -> LLMBudgetPolicy:
        self.policy = policy
        return policy

    async def reserve(
        self,
        *,
        task_id: UUID,
        profile_id: UUID,
        window_date: object,
        pricing: ModelPricing,
        input_tokens: int,
        output_tokens: int,
        cost: Decimal,
        policy: LLMBudgetPolicy,
    ) -> LLMBudgetReservation | None:
        current = sum(
            item.reserved_input_tokens + item.reserved_output_tokens for item in self.reservations
        )
        if current + input_tokens + output_tokens > policy.daily_token_limit:
            return None
        reservation = LLMBudgetReservation(
            uuid4(), task_id, profile_id, window_date, pricing, input_tokens, output_tokens, cost
        )
        self.reservations.append(reservation)
        return reservation

    async def reconcile(
        self,
        reservation: LLMBudgetReservation,
        *,
        input_tokens: int,
        output_tokens: int,
        cost: Decimal,
    ) -> None:
        return None

    async def usage(self, *, window_date: object, policy: LLMBudgetPolicy) -> LLMBudgetUsage:
        return LLMBudgetUsage(window_date, 0, 0, Decimal("0"), 0, Decimal("0"))


def profile(**values: object) -> ModelProviderProfile:
    data: dict[str, object] = {
        "id": uuid4(),
        "name": "synthetic",
        "provider_type": "OPENAI_COMPATIBLE",
        "base_url": "https://models.example",
        "model_name": "synthetic",
        "credential_ref": None,
        "timeout_seconds": 30,
        "max_tokens": 10,
        "enabled": True,
        "pricing_version": "TEST",
        "pricing_currency": "USD",
        "input_token_price": Decimal("0.01"),
        "output_token_price": Decimal("0.02"),
    }
    data.update(values)
    return ModelProviderProfile(**data)  # type: ignore[arg-type]


def request(task_id: UUID | None = None) -> LLMGatewayRequest:
    return LLMGatewayRequest(
        request_id=task_id or uuid4(),
        role=AgentRole.MACRO,
        prompt_bundle_hash="x",
        input_snapshot_hash="y",
        timeout_seconds=30,
        max_output_tokens=10,
        system_instruction="system",
        input_payload_json="{}",
    )


async def test_budget_fails_closed_without_policy_or_pricing() -> None:
    def now() -> datetime:
        return datetime(2026, 9, 22, tzinfo=UTC)

    service = LLMBudgetService(MemoryBudgetPort(None), now=now)
    with pytest.raises(LLMGatewayFailure, match="policy"):
        await service.reserve(profile=profile(), request=request())
    policy = LLMBudgetPolicy("TEST_DEFAULT", "USD", 1000, 1000, Decimal("10"), Decimal("10"))
    service = LLMBudgetService(MemoryBudgetPort(policy), now=now)
    with pytest.raises(LLMGatewayFailure, match="pricing"):
        await service.reserve(profile=profile(pricing_version=None), request=request())


async def test_repairs_share_task_budget_and_daily_capacity_is_reserved() -> None:
    policy = LLMBudgetPolicy("TEST_DEFAULT", "USD", 1000, 300, Decimal("10"), Decimal("10"))
    service = LLMBudgetService(
        MemoryBudgetPort(policy), now=lambda: datetime(2026, 9, 22, tzinfo=UTC)
    )
    task_id = uuid4()
    await service.reserve(profile=profile(), request=request(task_id))
    with pytest.raises(LLMGatewayFailure, match="exceed"):
        await service.reserve(profile=profile(), request=request(task_id))
