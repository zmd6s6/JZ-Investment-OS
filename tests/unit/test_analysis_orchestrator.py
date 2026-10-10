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
async def test_execute_analysis_succeeds_with_synthetic_inputs() -> None:
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

    result = await execute_analysis(request, committee=committee, market_data=adapter)
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
    assert payload["risk"]["gate"] in {"PASS", "VETO", "UNKNOWN"}
    assert payload["policy_version_label"] == "TEST_DEFAULT"


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
