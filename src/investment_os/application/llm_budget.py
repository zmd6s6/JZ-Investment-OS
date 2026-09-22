"""Deterministic, fail-closed LLM token and cost budget governance."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from investment_os.application.llm_gateway import LLMGatewayFailure, LLMGatewayRequest
from investment_os.application.provider_settings import ModelProviderProfile


@dataclass(frozen=True, slots=True)
class LLMBudgetPolicy:
    version: str
    currency: str
    task_token_limit: int
    daily_token_limit: int
    task_cost_limit: Decimal
    daily_cost_limit: Decimal


@dataclass(frozen=True, slots=True)
class ModelPricing:
    version: str
    currency: str
    input_token_price: Decimal
    output_token_price: Decimal


@dataclass(frozen=True, slots=True)
class LLMBudgetReservation:
    id: UUID
    task_id: UUID
    profile_id: UUID
    window_date: date
    pricing: ModelPricing
    reserved_input_tokens: int
    reserved_output_tokens: int
    reserved_cost: Decimal


@dataclass(frozen=True, slots=True)
class LLMBudgetUsage:
    window_date: date
    input_tokens: int
    output_tokens: int
    total_cost: Decimal
    remaining_tokens: int
    remaining_cost: Decimal
    reserved_tokens: int = 0
    reserved_cost: Decimal = Decimal("0")


class LLMBudgetPort(Protocol):
    async def get_policy(self) -> LLMBudgetPolicy | None: ...

    async def save_policy(self, policy: LLMBudgetPolicy) -> LLMBudgetPolicy: ...

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
    ) -> LLMBudgetReservation | None: ...

    async def reconcile(
        self,
        reservation: LLMBudgetReservation,
        *,
        input_tokens: int,
        output_tokens: int,
        cost: Decimal,
    ) -> None: ...

    async def usage(self, *, window_date: date, policy: LLMBudgetPolicy) -> LLMBudgetUsage: ...


class LLMBudgetService:
    """Reserve worst-case capacity before egress and reconcile only verified provider usage."""

    def __init__(self, port: LLMBudgetPort, *, now: Callable[[], datetime] | None = None) -> None:
        self._port = port
        self._now = now or (lambda: datetime.now(UTC))

    async def policy(self) -> LLMBudgetPolicy | None:
        return await self._port.get_policy()

    async def save_policy(self, policy: LLMBudgetPolicy) -> LLMBudgetPolicy:
        _validate_policy(policy)
        return await self._port.save_policy(policy)

    async def reserve(
        self, *, profile: ModelProviderProfile, request: LLMGatewayRequest
    ) -> LLMBudgetReservation:
        policy = await self._port.get_policy()
        if policy is None:
            raise LLMGatewayFailure("LLM budget policy is unavailable")
        _validate_policy(policy)
        pricing = _pricing_for(profile)
        if pricing.currency != policy.currency:
            raise LLMGatewayFailure("model pricing currency does not match the budget policy")
        input_tokens = _worst_case_input_tokens(request)
        output_tokens = min(profile.max_tokens, request.max_output_tokens)
        cost = (Decimal(input_tokens) * pricing.input_token_price) + (
            Decimal(output_tokens) * pricing.output_token_price
        )
        reservation = await self._port.reserve(
            task_id=request.request_id,
            profile_id=profile.id,
            window_date=self._now().astimezone(UTC).date(),
            pricing=pricing,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            policy=policy,
        )
        if reservation is None:
            raise LLMGatewayFailure("LLM request would exceed a task or daily budget")
        return reservation

    async def reconcile(
        self,
        reservation: LLMBudgetReservation,
        *,
        input_tokens: int,
        output_tokens: int,
    ) -> Decimal:
        if input_tokens < 0 or output_tokens < 0:
            raise LLMGatewayFailure("provider usage must not be negative")
        if (
            input_tokens > reservation.reserved_input_tokens
            or output_tokens > reservation.reserved_output_tokens
        ):
            raise LLMGatewayFailure("provider usage exceeded the reserved budget capacity")
        cost = (Decimal(input_tokens) * reservation.pricing.input_token_price) + (
            Decimal(output_tokens) * reservation.pricing.output_token_price
        )
        await self._port.reconcile(
            reservation,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
        )
        return cost

    async def usage(self) -> LLMBudgetUsage | None:
        policy = await self._port.get_policy()
        if policy is None:
            return None
        _validate_policy(policy)
        return await self._port.usage(
            window_date=self._now().astimezone(UTC).date(),
            policy=policy,
        )


def _pricing_for(profile: ModelProviderProfile) -> ModelPricing:
    if (
        profile.pricing_version is None
        or profile.pricing_currency is None
        or profile.input_token_price is None
        or profile.output_token_price is None
    ):
        raise LLMGatewayFailure("model pricing is unavailable")
    pricing = ModelPricing(
        version=profile.pricing_version,
        currency=profile.pricing_currency,
        input_token_price=profile.input_token_price,
        output_token_price=profile.output_token_price,
    )
    if not pricing.version.strip() or not pricing.currency.strip():
        raise LLMGatewayFailure("model pricing is unavailable")
    if pricing.input_token_price < 0 or pricing.output_token_price < 0:
        raise LLMGatewayFailure("model pricing is invalid")
    return pricing


def _worst_case_input_tokens(request: LLMGatewayRequest) -> int:
    if request.system_instruction is None or request.input_payload_json is None:
        raise LLMGatewayFailure("configured model runtime requires rendered prompt input")
    return (
        len(request.system_instruction.encode("utf-8"))
        + len(request.input_payload_json.encode("utf-8"))
        + 256
    )


def _validate_policy(policy: LLMBudgetPolicy) -> None:
    if (
        not policy.version.strip()
        or not policy.currency.strip()
        or policy.task_token_limit <= 0
        or policy.daily_token_limit <= 0
        or policy.task_cost_limit < 0
        or policy.daily_cost_limit < 0
    ):
        raise ValueError("LLM budget policy is invalid")
