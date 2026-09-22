"""OpenAI-compatible implementation of the bounded application LLM gateway port."""

from __future__ import annotations

import json
from dataclasses import replace
from time import monotonic
from typing import Any
from urllib.parse import urlparse

import httpx

from investment_os.application.llm_budget import LLMBudgetService
from investment_os.application.llm_gateway import (
    LLMGatewayFailure,
    LLMGatewayPort,
    LLMGatewayRequest,
    LLMGatewayResponse,
)
from investment_os.application.provider_settings import (
    ModelProviderProfile,
    ProviderSettingsService,
    ProviderTestResult,
)
from investment_os.application.secrets import SecretStore

_OPENAI_COMPATIBLE = "OPENAI_COMPATIBLE"
_TEST_MAX_OUTPUT_TOKENS = 16


class OpenAICompatibleLLMGateway(LLMGatewayPort):
    """Call an owner-configured compatible endpoint without exposing credentials to callers."""

    def __init__(
        self,
        *,
        provider_settings: ProviderSettingsService,
        secret_store: SecretStore,
        budget_service: LLMBudgetService,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._provider_settings = provider_settings
        self._secret_store = secret_store
        self._budget_service = budget_service
        self._client = client or httpx.AsyncClient(follow_redirects=False)
        self._owns_client = client is None

    async def close(self) -> None:
        """Close the owned HTTP client during application shutdown."""

        if self._owns_client:
            await self._client.aclose()

    async def complete(self, request: LLMGatewayRequest) -> LLMGatewayResponse:
        try:
            profile = await self._provider_settings.model_for_role(request.role.value)
        except (LookupError, ValueError) as exc:
            raise LLMGatewayFailure("configured model provider is unavailable") from exc
        credential = await self._credential_for(profile)
        if request.system_instruction is None or request.input_payload_json is None:
            raise LLMGatewayFailure(
                "configured model runtime requires a rendered system instruction and JSON input"
            )
        try:
            input_payload = json.loads(request.input_payload_json)
        except (TypeError, ValueError) as exc:
            raise LLMGatewayFailure(
                "configured model runtime received an invalid JSON input"
            ) from exc
        if not isinstance(input_payload, dict):
            raise LLMGatewayFailure("configured model runtime requires a JSON object input")
        reservation = await self._budget_service.reserve(profile=profile, request=request)
        response = await self._complete(
            profile=profile,
            credential=credential,
            system_instruction=request.system_instruction,
            input_payload={
                "protocol_version": request.protocol_version,
                "role": request.role.value,
                "repair_attempt": request.repair_attempt,
                "repair_error_code": request.repair_error_code,
                "input": input_payload,
            },
            max_tokens=min(profile.max_tokens, request.max_output_tokens),
            timeout_seconds=min(profile.timeout_seconds, request.timeout_seconds),
        )
        try:
            cost = await self._budget_service.reconcile(
                reservation,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            )
        except (RuntimeError, LLMGatewayFailure) as exc:
            raise LLMGatewayFailure("LLM budget reconciliation failed") from exc
        return replace(
            response,
            total_cost=cost,
            pricing_version=reservation.pricing.version,
            budget_window_date=reservation.window_date.isoformat(),
        )

    async def test_connection(
        self, *, profile: ModelProviderProfile, credential: str
    ) -> ProviderTestResult:
        """Verify authentication and JSON-object output with no portfolio or Evidence data."""

        if profile.provider_type != _OPENAI_COMPATIBLE:
            return ProviderTestResult(
                status="UNSUPPORTED_PROVIDER",
                detail="P3 仅支持 OPENAI_COMPATIBLE 模型提供方。未发起网络请求。",
            )
        try:
            from uuid import uuid4

            from investment_os.domain.agent import AgentRole

            request = LLMGatewayRequest(
                request_id=uuid4(),
                role=AgentRole.MACRO,
                prompt_bundle_hash="connection-test",
                input_snapshot_hash="connection-test",
                timeout_seconds=profile.timeout_seconds,
                max_output_tokens=min(profile.max_tokens, _TEST_MAX_OUTPUT_TOKENS),
                system_instruction=(
                    '这是连接测试。只能返回 JSON 对象 {"status":"ok"}。不得执行建议或模拟任何交易。'
                ),
                input_payload_json='{"connection_test":true}',
            )
            reservation = await self._budget_service.reserve(profile=profile, request=request)
            system_instruction = request.system_instruction
            if system_instruction is None:
                raise LLMGatewayFailure("connection test prompt is unavailable")
            response = await self._complete(
                profile=profile,
                credential=credential,
                system_instruction=system_instruction,
                input_payload={"connection_test": True},
                max_tokens=request.max_output_tokens,
                timeout_seconds=profile.timeout_seconds,
            )
            await self._budget_service.reconcile(
                reservation,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            )
            payload = json.loads(response.raw_output)
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                return ProviderTestResult(
                    status="CONNECTION_FAILED",
                    detail="模型未返回预期的结构化连接测试结果",
                    latency_ms=response.latency_ms,
                )
        except (LLMGatewayFailure, ValueError):
            return ProviderTestResult(
                status="CONNECTION_FAILED",
                detail="模型连接认证或结构化输出检查失败。详细信息已脱敏。",
            )
        return ProviderTestResult(
            status="CONNECTION_SUCCEEDED",
            detail="模型连接、认证和 JSON 对象输出检查通过",
            latency_ms=response.latency_ms,
        )

    async def _credential_for(self, profile: ModelProviderProfile) -> str:
        if profile.provider_type != _OPENAI_COMPATIBLE:
            raise LLMGatewayFailure("configured model provider type is unsupported")
        if profile.credential_ref is None:
            raise LLMGatewayFailure("configured model provider credential is unavailable")
        try:
            credential = await self._secret_store.get(profile.credential_ref)
        except RuntimeError as exc:
            raise LLMGatewayFailure("configured model provider credential is unavailable") from exc
        if credential is None:
            raise LLMGatewayFailure("configured model provider credential is unavailable")
        return credential

    async def _complete(
        self,
        *,
        profile: ModelProviderProfile,
        credential: str,
        system_instruction: str,
        input_payload: dict[str, Any],
        max_tokens: int,
        timeout_seconds: int,
    ) -> LLMGatewayResponse:
        _validate_profile(profile)
        started = monotonic()
        try:
            response = await self._client.post(
                f"{profile.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {credential}"},
                json={
                    "model": profile.model_name,
                    "messages": [
                        {"role": "system", "content": system_instruction},
                        {
                            "role": "user",
                            "content": json.dumps(
                                input_payload,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        },
                    ],
                    "temperature": 0,
                    "max_tokens": max_tokens,
                    "response_format": {"type": "json_object"},
                },
                timeout=httpx.Timeout(timeout_seconds),
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMGatewayFailure("model provider request failed") from exc
        latency_ms = int((monotonic() - started) * 1000)
        try:
            raw_output = payload["choices"][0]["message"]["content"]
            usage = payload.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
            actual_model_name = payload.get("model", profile.model_name)
        except (AttributeError, IndexError, KeyError, TypeError) as exc:
            raise LLMGatewayFailure("model provider returned an invalid response schema") from exc
        if (
            not isinstance(raw_output, str)
            or not isinstance(input_tokens, int)
            or not isinstance(output_tokens, int)
            or input_tokens < 0
            or output_tokens < 0
            or not isinstance(actual_model_name, str)
            or not actual_model_name.strip()
        ):
            raise LLMGatewayFailure("model provider returned invalid usage or output fields")
        if output_tokens > max_tokens:
            raise LLMGatewayFailure(
                "model provider response exceeded the configured output-token budget"
            )
        return LLMGatewayResponse(
            raw_output=raw_output,
            provider=profile.name,
            model_name=actual_model_name,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def _validate_profile(profile: ModelProviderProfile) -> None:
    if profile.provider_type != _OPENAI_COMPATIBLE:
        raise LLMGatewayFailure("configured model provider type is unsupported")
    parsed = urlparse(profile.base_url)
    hostname = parsed.hostname
    if parsed.scheme == "https" and hostname:
        return
    if parsed.scheme == "http" and hostname in {"127.0.0.1", "localhost", "::1"}:
        return
    raise LLMGatewayFailure(
        "model provider endpoint must use HTTPS unless it is an explicit loopback endpoint"
    )
