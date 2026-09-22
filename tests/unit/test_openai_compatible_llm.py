import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest

from investment_os.application.agent_registry import AgentRoleRegistry, PromptBundle
from investment_os.application.agent_runtime import AgentRunFailure, AgentRuntime
from investment_os.application.analysis_context import AnalysisEvidence, freeze_analysis_context
from investment_os.application.llm_budget import (
    LLMBudgetPolicy,
    LLMBudgetReservation,
    LLMBudgetService,
    LLMBudgetUsage,
)
from investment_os.application.llm_gateway import LLMGatewayRequest
from investment_os.application.provider_settings import (
    DataProviderProfile,
    ModelProviderProfile,
    ProviderSettingsService,
    ProviderTestResult,
    RoleModelAssignment,
    SystemSettings,
)
from investment_os.domain.agent import AgentRole, AgentTool, OpinionStance
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.openai_compatible_llm import OpenAICompatibleLLMGateway


class MemorySecretStore:
    def __init__(self) -> None:
        self.values: dict[UUID, str] = {}

    async def put(self, credential_ref: UUID, value: str) -> None:
        self.values[credential_ref] = value

    async def get(self, credential_ref: UUID) -> str | None:
        return self.values.get(credential_ref)

    async def delete(self, credential_ref: UUID) -> None:
        self.values.pop(credential_ref, None)


class MemoryProviderSettingsPort:
    def __init__(self) -> None:
        self.models: dict[UUID, ModelProviderProfile] = {}
        self.assignments: dict[str, RoleModelAssignment] = {}
        self.recorded_tests: list[ProviderTestResult] = []

    async def get_system_settings(self) -> SystemSettings:
        return SystemSettings(market_timezone="Asia/Shanghai", market_scopes=())

    async def save_system_settings(self, settings: SystemSettings) -> SystemSettings:
        return settings

    async def list_model_profiles(self) -> list[ModelProviderProfile]:
        return list(self.models.values())

    async def get_model_profile(self, profile_id: UUID) -> ModelProviderProfile | None:
        return self.models.get(profile_id)

    async def save_model_profile(self, profile: ModelProviderProfile) -> ModelProviderProfile:
        self.models[profile.id] = profile
        return profile

    async def delete_model_profile(self, profile_id: UUID) -> bool:
        return self.models.pop(profile_id, None) is not None

    async def list_data_profiles(self) -> list[DataProviderProfile]:
        return []

    async def get_data_profile(self, profile_id: UUID) -> DataProviderProfile | None:
        return None

    async def save_data_profile(self, profile: DataProviderProfile) -> DataProviderProfile:
        return profile

    async def delete_data_profile(self, profile_id: UUID) -> bool:
        return False

    async def list_role_assignments(self) -> list[RoleModelAssignment]:
        return list(self.assignments.values())

    async def save_role_assignment(self, assignment: RoleModelAssignment) -> RoleModelAssignment:
        self.assignments[assignment.role] = assignment
        return assignment

    async def delete_role_assignment(self, role: str) -> bool:
        return self.assignments.pop(role, None) is not None

    async def record_provider_test(
        self, *, profile_id: UUID, provider_kind: str, result: ProviderTestResult
    ) -> None:
        self.recorded_tests.append(result)


class MemoryBudgetPort:
    def __init__(self) -> None:
        self.policy = LLMBudgetPolicy(
            "TEST_DEFAULT", "USD", 10000, 10000, Decimal("10"), Decimal("10")
        )

    async def get_policy(self):
        return self.policy

    async def save_policy(self, policy):
        self.policy = policy
        return policy

    async def reserve(self, **values):
        return LLMBudgetReservation(
            uuid4(),
            values["task_id"],
            values["profile_id"],
            values["window_date"],
            values["pricing"],
            values["input_tokens"],
            values["output_tokens"],
            values["cost"],
        )

    async def reconcile(self, reservation, **values):
        return None

    async def usage(self, **values):
        return LLMBudgetUsage(values["window_date"], 0, 0, Decimal("0"), 10000, Decimal("10"))


async def _configured_gateway(
    *,
    handler: httpx.MockTransport,
    base_url: str = "https://models.example.test/v1",
) -> tuple[OpenAICompatibleLLMGateway, ProviderSettingsService, ModelProviderProfile]:
    port = MemoryProviderSettingsPort()
    secrets = MemorySecretStore()
    service = ProviderSettingsService(port, secrets)  # type: ignore[arg-type]
    profile = await service.save_model_profile(
        profile_id=None,
        name="authorized-test-provider",
        provider_type="OPENAI_COMPATIBLE",
        base_url=base_url,
        model_name="structured-test-model",
        timeout_seconds=20,
        max_tokens=100,
        enabled=True,
        credential="only-in-memory-test-credential",
        pricing_version="TEST_PRICING",
        pricing_currency="USD",
        input_token_price=Decimal("0.000001"),
        output_token_price=Decimal("0.000002"),
    )
    await service.save_role_assignment(role="DEFAULT", model_provider_profile_id=profile.id)
    return (
        OpenAICompatibleLLMGateway(
            provider_settings=service,
            secret_store=secrets,  # type: ignore[arg-type]
            budget_service=LLMBudgetService(MemoryBudgetPort()),  # type: ignore[arg-type]
            client=httpx.AsyncClient(transport=handler, follow_redirects=False),
        ),
        service,
        profile,
    )


def _request(**overrides: object) -> LLMGatewayRequest:
    values: dict[str, object] = {
        "request_id": uuid4(),
        "role": AgentRole.MACRO,
        "prompt_bundle_hash": "a" * 64,
        "input_snapshot_hash": "b" * 64,
        "timeout_seconds": 30,
        "max_output_tokens": 500,
        "system_instruction": "Return only the requested AgentOpinion JSON object.",
        "input_payload_json": '{"synthetic_evidence":[{"id":"evidence-1"}]}',
    }
    values.update(overrides)
    return LLMGatewayRequest(**values)  # type: ignore[arg-type]


async def test_openai_compatible_gateway_routes_role_and_enforces_profile_budgets() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"schema_version":"1.0"}'}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
                "model": "provider-reported-model",
            },
        )

    gateway, _service, _profile = await _configured_gateway(handler=httpx.MockTransport(handler))
    response = await gateway.complete(_request())

    assert response.provider == "authorized-test-provider"
    assert response.model_name == "provider-reported-model"
    assert response.input_tokens == 7
    assert captured["url"] == "https://models.example.test/v1/chat/completions"
    assert captured["authorization"] == "Bearer only-in-memory-test-credential"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["max_tokens"] == 100
    assert body["response_format"] == {"type": "json_object"}
    assert json.loads(body["messages"][1]["content"])["input"] == {
        "synthetic_evidence": [{"id": "evidence-1"}]
    }


async def test_connection_check_is_explicit_and_persists_only_sanitized_result() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        assert request.headers["Authorization"] == "Bearer only-in-memory-test-credential"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"status":"ok"}'}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    gateway, service, profile = await _configured_gateway(handler=httpx.MockTransport(handler))

    result = await service.test_model_profile(profile.id, connection_tester=gateway)

    assert result.status == "CONNECTION_SUCCEEDED"
    assert result.latency_ms is not None
    assert request_count == 1


async def test_gateway_rejects_non_tls_external_endpoint_before_sending_credential() -> None:
    gateway, _service, _profile = await _configured_gateway(
        handler=httpx.MockTransport(lambda _: pytest.fail("request must not be sent")),
        base_url="http://models.example.test/v1",
    )

    with pytest.raises(RuntimeError, match="HTTPS"):
        await gateway.complete(_request())


async def test_gateway_rejects_provider_output_that_exceeds_the_configured_budget() -> None:
    gateway, _service, _profile = await _configured_gateway(
        handler=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "{}"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 101},
                },
            )
        )
    )

    with pytest.raises(RuntimeError, match="output-token budget"):
        await gateway.complete(_request(max_output_tokens=500))


@pytest.mark.parametrize(
    "usage",
    (
        None,
        {"prompt_tokens": 1},
        {"completion_tokens": 1},
        {"prompt_tokens": None, "completion_tokens": 1},
        {"prompt_tokens": "1", "completion_tokens": 1},
        {"prompt_tokens": -1, "completion_tokens": 1},
    ),
)
async def test_gateway_rejects_unverifiable_provider_usage_without_reconciliation(
    usage: dict[str, object] | None,
) -> None:
    payload: dict[str, object] = {"choices": [{"message": {"content": "{}"}}]}
    if usage is not None:
        payload["usage"] = usage
    gateway, _service, _profile = await _configured_gateway(
        handler=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )

    with pytest.raises(RuntimeError, match="invalid usage"):
        await gateway.complete(_request())


async def test_agent_runtime_preserves_fail_closed_agent_opinion_path_with_configured_gateway() -> (
    None
):
    instrument_id = uuid4()
    evidence_id = uuid4()
    as_of = datetime(2026, 9, 22, tzinfo=UTC)
    context = freeze_analysis_context(
        instrument_id,
        as_of=as_of,
        evidence=(
            AnalysisEvidence(
                evidence_id=evidence_id,
                content_hash="b" * 64,
                available_at=UtcTimestamp(as_of),
            ),
        ),
    )
    opinion_payload = {
        "schema_version": "1.0",
        "agent_role": "MACRO",
        "instrument_id": str(instrument_id),
        "as_of": as_of.isoformat(),
        "stance": "POSITIVE",
        "confidence": "0.5",
        "time_horizon": "DAYS",
        "observations": [
            {
                "claim": "Synthetic fixture fact",
                "evidence_ids": [str(evidence_id)],
                "materiality": "MEDIUM",
            }
        ],
        "thesis_impacts": [],
        "assumptions": [],
        "risks": [],
        "invalidation_conditions": [],
        "unknowns": [],
        "requested_followups": [],
    }

    gateway, _service, _profile = await _configured_gateway(
        handler=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": json.dumps(opinion_payload)}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 5},
                },
            )
        )
    )
    runtime = AgentRuntime(
        registry=AgentRoleRegistry(
            (
                PromptBundle(
                    role=AgentRole.MACRO,
                    version="v1",
                    content_hash="a" * 64,
                    allowed_tools=(AgentTool.RETRIEVE_EVIDENCE,),
                ),
            )
        ),
        gateway=gateway,
    )

    result = await runtime.run(
        request=_request(
            input_snapshot_hash=context.input_snapshot_hash,
            input_payload_json=json.dumps(
                {"evidence_ids": [str(evidence_id)]},
                separators=(",", ":"),
            ),
        ),
        context=context,
    )

    assert result.failure is None
    assert result.opinion.stance is OpinionStance.POSITIVE
    assert result.attempts[0].provider == "authorized-test-provider"


async def test_agent_runtime_converts_configured_provider_failure_to_insufficient_data() -> None:
    gateway, _service, _profile = await _configured_gateway(
        handler=httpx.MockTransport(lambda _: httpx.Response(401, text="not logged"))
    )
    instrument_id = uuid4()
    as_of = datetime(2026, 9, 22, tzinfo=UTC)
    context = freeze_analysis_context(
        instrument_id,
        as_of=as_of,
        evidence=(
            AnalysisEvidence(
                evidence_id=uuid4(),
                content_hash="b" * 64,
                available_at=UtcTimestamp(as_of),
            ),
        ),
    )
    runtime = AgentRuntime(
        registry=AgentRoleRegistry(
            (
                PromptBundle(
                    role=AgentRole.MACRO,
                    version="v1",
                    content_hash="a" * 64,
                    allowed_tools=(AgentTool.RETRIEVE_EVIDENCE,),
                ),
            )
        ),
        gateway=gateway,
    )

    result = await runtime.run(
        request=_request(input_snapshot_hash=context.input_snapshot_hash),
        context=context,
    )

    assert result.failure is AgentRunFailure.GATEWAY_FAILURE
    assert result.opinion.stance is OpinionStance.INSUFFICIENT_DATA
