"""PRODUCT-06 analysis orchestration unit tests with synthetic LLM and quotes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from investment_os.application.agent_runtime import AgentRuntime
from investment_os.application.analysis_orchestrator import (
    AnalysisEvidenceSource,
    AnalysisRequest,
    execute_analysis,
)
from investment_os.application.committee import ROUND_ONE_ROLES
from investment_os.application.committee_runtime import CommitteeRuntime
from investment_os.application.llm_gateway import LLMGatewayResponse, SyntheticLLMGateway
from investment_os.application.market_data import InMemoryMarketDataAdapter, MarketQuote
from investment_os.application.portfolio_book import PortfolioPositionView, PortfolioView
from investment_os.domain.agent import AgentRole
from investment_os.domain.enums import ThesisState

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
PROMPT_HASH_PREFIX = "p6"


def _opinion_json(role: AgentRole, stance: str, evidence_id: str) -> str:
    return (
        "{"
        '"schema_version":"1.0",'
        f'"agent_role":"{role.value}",'
        f'"instrument_id":"{evidence_id}",'
        '"as_of":"' + NOW.isoformat() + '",'
        f'"stance":"{stance}",'
        '"confidence":"0.6",'
        '"time_horizon":"DAYS",'
        '"observations":[{"claim":"Synthetic fact",'
        f'"evidence_ids":["{evidence_id}"],"materiality":"MEDIUM"}}'
        if False
        else (
            "{"
            '"schema_version":"1.0",'
            f'"agent_role":"{role.value}",'
            f'"instrument_id":"{role}",'
            f'"as_of":"{NOW.isoformat()}",'
            f'"stance":"{stance}",'
            '"confidence":"0.6",'
            '"time_horizon":"DAYS",'
            '"observations":[{"claim":"Synthetic fact",'
            f'"evidence_ids":["{evidence_id}"],"materiality":"MEDIUM"}}'
            "}]"
            if False
            else _correct_json(role, stance, evidence_id)
        )
        + "}"
    )


def _correct_json(role: AgentRole, stance: str, evidence_id: str) -> str:
    import json

    # instrument_id must match context — replaced by caller wrapper
    payload = {
        "schema_version": "1.0",
        "agent_role": role.value,
        "instrument_id": "",
        "as_of": NOW.isoformat(),
        "stance": stance,
        "confidence": "0.6",
        "time_horizon": "DAYS",
        "observations": [
            {
                "claim": "Synthetic fact",
                "evidence_ids": [evidence_id],
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
    return json.dumps(payload, separators=(",", ":"))


def _response(
    role: AgentRole, stance: str, instrument_id: str, evidence_id: str
) -> LLMGatewayResponse:
    import json

    payload = {
        "schema_version": "1.0",
        "agent_role": role.value,
        "instrument_id": str(instrument_id),
        "as_of": NOW.isoformat(),
        "stance": stance,
        "confidence": "0.6",
        "time_horizon": "DAYS",
        "observations": [
            {
                "claim": "Synthetic evidence-backed fact",
                "evidence_ids": [evidence_id],
                "materiality": "MEDIUM",
            }
        ],
        "thesis_impacts": [],
        "assumptions": [],
        "risks": (
            [
                {
                    "code": "SYNTHETIC_SOFT_RISK",
                    "severity": "LOW",
                    "evidence_ids": [evidence_id],
                }
            ]
            if role is AgentRole.RISK
            else []
        ),
        "invalidation_conditions": [],
        "unknowns": ["No additional unknowns"],
        "requested_followups": [],
    }
    return LLMGatewayResponse(
        raw_output=json.dumps(payload, separators=(",", ":")),
        provider="synthetic",
        model_name="fixture-v1",
        latency_ms=1,
        input_tokens=10,
        output_tokens=20,
    )


def _portfolio(instrument_id: object) -> PortfolioView:
    return PortfolioView(
        portfolio_id=uuid4(),
        name="合成测试组合",
        base_currency="CNY",
        cash_balance=Decimal("10000"),
        status="ACTIVE",
        positions=(
            PortfolioPositionView(
                position_id=uuid4(),
                instrument_id=instrument_id,  # type: ignore[arg-type]
                market="SSE",
                symbol="600519",
                name="贵州茅台",
                asset_type="EQUITY",
                currency="CNY",
                sector="Consumer",
                core_quantity=Decimal("10"),
                tactical_quantity=Decimal("0"),
                average_cost=Decimal("1600"),
            ),
        ),
    )


@pytest.mark.asyncio
async def test_execute_analysis_succeeds_with_synthetic_inputs(monkeypatch) -> None:
    from investment_os.application.analysis_orchestrator import default_registry

    instrument_id = uuid4()
    evidence_id = uuid4()
    evidence_hash = "c" * 64

    registry = default_registry()
    roles_round_one = ROUND_ONE_ROLES
    extra_roles = (AgentRole.DEVILS_ADVOCATE, AgentRole.PORTFOLIO, AgentRole.RISK)
    stances = {
        AgentRole.MACRO: "NEUTRAL",
        AgentRole.INDUSTRY: "NEUTRAL",
        AgentRole.FUNDAMENTAL: "POSITIVE",
        AgentRole.MARKET_QUANT: "POSITIVE",
        AgentRole.EVENT: "NEUTRAL",
        AgentRole.DEVILS_ADVOCATE: "NEUTRAL",
        AgentRole.PORTFOLIO: "NEUTRAL",
        AgentRole.RISK: "NEUTRAL",
    }
    responses = tuple(
        _response(role, stances[role], str(instrument_id), str(evidence_id))
        for role in roles_round_one + extra_roles
    )
    gateway = SyntheticLLMGateway(responses)
    calls = []
    complete = gateway.complete

    async def capture(req):
        calls.append(req)
        return await complete(req)

    monkeypatch.setattr(gateway, "complete", capture)
    committee = CommitteeRuntime(agent_runtime=AgentRuntime(registry=registry, gateway=gateway))

    adapter = InMemoryMarketDataAdapter()
    adapter.put(
        MarketQuote(
            instrument_id=instrument_id,  # type: ignore[arg-type]
            reference_price=Decimal("1500"),
            currency="CNY",
            as_of=NOW - timedelta(minutes=1),
            source="SYNTHETIC_TEST",
        )
    )

    request = AnalysisRequest(
        instrument_id=instrument_id,  # type: ignore[arg-type]
        portfolio_id=uuid4(),
        portfolio=_portfolio(instrument_id),  # type: ignore[arg-type]
        as_of=NOW,
        policy_version_label="TEST_DEFAULT",
        evidence=(
            AnalysisEvidenceSource(
                evidence_id=evidence_id,
                content_hash=evidence_hash,
                available_at=NOW - timedelta(hours=1),
                source_tier="PRIMARY",
            ),
        ),
        thesis_state=ThesisState.VALID,
    )

    events = []
    quote_calls = []
    get_quotes = adapter.get_reference_quotes

    async def capture_quotes(*args, **kwargs):
        quote_calls.append(args)
        return await get_quotes(*args, **kwargs)

    monkeypatch.setattr(adapter, "get_reference_quotes", capture_quotes)

    async def progress(stage, state):
        events.append((stage, state))

    result = await execute_analysis(
        request, committee=committee, market_data=adapter, progress=progress
    )
    assert result.status == "SUCCEEDED"
    assert result.payload is not None
    payload = result.payload.to_dict()
    assert payload["decision"]["action"] in {
        "WATCH",
        "BUY",
        "ADD",
        "HOLD",
        "REDUCE",
        "EXIT",
        "AVOID",
    }
    assert len(payload["opinions"]) == 8  # 5 specialists + DA + PM + RISK
    assert payload["valuation"]["status"] == "OK"
    assert payload["sizing"]["status"] == "BLOCKED"
    assert "target_quantity" not in payload["sizing"]
    assert "SIZING_CONTEXT_INCOMPLETE" in payload["failures"]
    assert "INSUFFICIENT_VALUATION_FOR_EXPOSURE" in payload["failures"]
    assert payload["decision"]["action"] not in {"BUY", "ADD"}
    import json

    assert len(quote_calls) == 1 and len(calls) == 8
    assert all(r.input_snapshot_hash == payload["context_hash"] for r in calls)
    assert all(
        json.loads(r.input_payload_json)["deterministic_portfolio_context"]["valuation"]
        == payload["valuation"]
        for r in calls
    )
    assert payload["risk"]["gate"] in {"PASS", "VETO", "UNKNOWN"}
    assert payload["policy_version_label"] == "TEST_DEFAULT"
    assert events == [
        (stage, state)
        for stage in (
            "PREPARING",
            "ROUND_ONE",
            "CONFLICTS",
            "ROUND_TWO",
            "PORTFOLIO",
            "RISK",
            "VALUATION_SIZING",
            "CIO",
        )
        for state in ("STARTED", "COMPLETED")
    ]


@pytest.mark.asyncio
async def test_valuation_failure_blocks_buy_not_succeeded_buy() -> None:
    from investment_os.application.agent_runtime import AgentRuntime as AR
    from investment_os.application.analysis_orchestrator import default_registry
    from investment_os.application.committee_runtime import CommitteeRuntime as CR

    instrument_id = uuid4()
    evidence_id = uuid4()
    stances = {
        AgentRole.MACRO: "NEUTRAL",
        AgentRole.INDUSTRY: "NEUTRAL",
        AgentRole.FUNDAMENTAL: "POSITIVE",
        AgentRole.MARKET_QUANT: "POSITIVE",
        AgentRole.EVENT: "NEUTRAL",
        AgentRole.DEVILS_ADVOCATE: "NEUTRAL",
        AgentRole.PORTFOLIO: "NEUTRAL",
        AgentRole.RISK: "NEUTRAL",
    }
    responses = tuple(
        _response(role, stances[role], str(instrument_id), str(evidence_id))
        for role in (
            *ROUND_ONE_ROLES,
            AgentRole.DEVILS_ADVOCATE,
            AgentRole.PORTFOLIO,
            AgentRole.RISK,
        )
    )
    committee = CR(
        agent_runtime=AR(registry=default_registry(), gateway=SyntheticLLMGateway(responses))
    )
    request = AnalysisRequest(
        instrument_id=instrument_id,  # type: ignore[arg-type]
        portfolio_id=uuid4(),
        portfolio=_portfolio(instrument_id),  # type: ignore[arg-type]
        as_of=NOW,
        policy_version_label="TEST_DEFAULT",
        evidence=(
            AnalysisEvidenceSource(
                evidence_id=evidence_id,
                content_hash="d" * 64,
                available_at=NOW - timedelta(hours=1),
            ),
        ),
        instrument_market="SSE",
        instrument_symbol="600519",
        instrument_currency="CNY",
    )
    # No market data quotes on purpose.
    result = await execute_analysis(
        request,
        committee=committee,
        market_data=InMemoryMarketDataAdapter(),
    )
    assert result.status == "SUCCEEDED"
    assert result.payload is not None
    decision = result.payload.to_dict()["decision"]
    assert decision["action"] != "BUY"
    assert "INSUFFICIENT_VALUATION_FOR_EXPOSURE" in result.payload.to_dict()["failures"]


@pytest.mark.asyncio
async def test_execute_analysis_fails_without_evidence() -> None:
    from investment_os.application.agent_runtime import AgentRuntime as AR
    from investment_os.application.analysis_orchestrator import default_registry
    from investment_os.application.committee_runtime import CommitteeRuntime as CR

    instrument_id = uuid4()
    registry = default_registry()
    gateway = SyntheticLLMGateway(())
    committee = CR(agent_runtime=AR(registry=registry, gateway=gateway))
    request = AnalysisRequest(
        instrument_id=instrument_id,  # type: ignore[arg-type]
        portfolio_id=uuid4(),
        portfolio=_portfolio(instrument_id),  # type: ignore[arg-type]
        as_of=NOW,
        policy_version_label="TEST_DEFAULT",
        evidence=(),
    )
    result = await execute_analysis(
        request,
        committee=committee,
        market_data=InMemoryMarketDataAdapter(),
    )
    assert result.status == "FAILED"
    assert result.failure_code == "INSUFFICIENT_EVIDENCE"


async def test_execution_context_commit_failure_stops_before_any_model(monkeypatch):
    from investment_os.application.analysis_execution_context import ExecutionContextFailure
    from investment_os.application.analysis_orchestrator import default_registry

    identity = uuid4()
    request = AnalysisRequest(
        identity,
        uuid4(),
        _portfolio(identity),
        NOW,
        "TEST_DEFAULT",
        (AnalysisEvidenceSource(uuid4(), "a" * 64, NOW - timedelta(hours=1)),),
    )
    gateway = SyntheticLLMGateway(())
    calls = []

    async def forbidden(request):
        calls.append(request)
        raise AssertionError("model must not be called")

    async def fail_context(value):
        raise ExecutionContextFailure("synthetic commit failure")

    monkeypatch.setattr(gateway, "complete", forbidden)
    result = await execute_analysis(
        request,
        committee=CommitteeRuntime(
            agent_runtime=AgentRuntime(registry=default_registry(), gateway=gateway)
        ),
        market_data=InMemoryMarketDataAdapter(),
        context_recorder=fail_context,
    )
    assert result.status == "FAILED" and result.failure_code == "ANALYSIS_CONTEXT_RECORDING_FAILED"
    assert calls == []


def test_agent_prompt_embeds_full_agentopinion_contract() -> None:
    """Regression: the provider must receive the Schema body, not just its name.

    deepseek-chat once invented its own envelope (wrapped ``opinion`` object,
    float confidence) when the system instruction only said ``schema 1.0``,
    exhausting both repair attempts on every role with INVALID_OUTPUT.
    """

    from investment_os.application.analysis_context import (
        AnalysisEvidence,
        EvidenceSourceTier,
        freeze_analysis_context,
    )
    from investment_os.application.analysis_orchestrator import (
        _AGENT_OPINION_SCHEMA_INSTRUCTION,
        build_analysis_request_factory,
        default_request_factory,
    )
    from investment_os.application.committee_runtime import CommitteeRoleInput
    from investment_os.domain.values import UtcTimestamp

    instruction = _AGENT_OPINION_SCHEMA_INSTRUCTION
    for required in (
        '"schema_version": "1.0"',
        '"agent_role"',
        '"confidence"',
        "NEVER a bare number",
        "STRONGLY_NEGATIVE|NEGATIVE|NEUTRAL|POSITIVE|STRONGLY_POSITIVE|INSUFFICIENT_DATA",
        "no wrapper key",
        "materiality",
        "invalidation_conditions",
        "requested_followups",
        "Stance mutual exclusion",
        'if stance is "INSUFFICIENT_DATA"',
        '"observations" must be []',
    ):
        assert required in instruction, f"schema instruction is missing: {required}"

    evidence_id = uuid4()
    context = freeze_analysis_context(
        uuid4(),  # type: ignore[arg-type]
        as_of=NOW,
        evidence=(
            AnalysisEvidence(
                evidence_id=evidence_id,  # type: ignore[arg-type]
                content_hash="e" * 64,
                available_at=UtcTimestamp(NOW - timedelta(hours=1)),
                source_tier=EvidenceSourceTier.PRIMARY,
                independence_key="f" * 32,
            ),
        ),
    )
    role_input = CommitteeRoleInput(context=context)

    default_request = default_request_factory(AgentRole.MACRO, role_input)
    assert default_request.system_instruction == instruction

    factory = build_analysis_request_factory(
        evidence=(
            AnalysisEvidenceSource(
                evidence_id=evidence_id,  # type: ignore[arg-type]
                content_hash="e" * 64,
                available_at=NOW - timedelta(hours=1),
                source_tier="PRIMARY",
            ),
        ),
        instrument_meta={"instrument_id": str(context.instrument_id), "market": "SSE"},
        portfolio_meta={},
        positions_meta=[],
    )
    full_request = factory(AgentRole.MACRO, role_input)
    assert full_request.system_instruction == instruction
    # The instruction itself must not be mistaken for the payload contract:
    # it names the confidence type the validator rejects (bare float).
    assert "NEVER a bare number" in instruction
