"""Fixed governance must describe actual inputs, not confer authority by a label."""

import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from investment_os.application.analysis_governance import FrozenAnalysisPolicy, policy_config_hash
from investment_os.application.analysis_jobs import AnalysisWorkItem
from investment_os.application.analysis_orchestrator import (
    DEFAULT_SIZING_FORMULA,
    AnalysisRequest,
    AnalysisRunResult,
    _build_valuation_and_sizing,
    _prompt_hash,
    freeze_governance,
)
from investment_os.application.analysis_product import ProductAnalysisService
from investment_os.application.analysis_thesis import AnalysisThesisInput
from investment_os.application.market_data import InMemoryMarketDataAdapter, MarketQuote
from investment_os.application.policy_schema import InvestmentPolicySchema
from investment_os.application.portfolio_book import PortfolioView
from investment_os.domain.agent import AgentRole
from investment_os.domain.enums import Action, RiskIntent, ThesisState
from investment_os.domain.risk import RiskAssessment, RiskFlag, RiskFlagKind, RiskSeverity
from investment_os.domain.values import UtcTimestamp

NOW = datetime(2026, 10, 20, 8, tzinfo=UTC)


def frozen_policy(*, active=False, cap="8"):
    payload = json.loads(
        Path("config/investment-policy.test-default.json").read_text(encoding="utf-8")
    )
    payload["position"]["single_instrument_max_pct"] = cap
    payload["metadata"]["status"] = "ACTIVE" if active else "TEST_DEFAULT"
    config = InvestmentPolicySchema.model_validate_json(json.dumps(payload))
    return FrozenAnalysisPolicy(
        mode="ACTIVE" if active else "TEST_DEFAULT",
        config=config,
        content_hash=policy_config_hash(config),
        version=1,
        **(
            {
                "policy_id": uuid4(),
                "policy_version_id": uuid4(),
                "approved_by": "synthetic-owner",
                "approved_by_actor": "HUMAN",
                "approved_at": NOW - timedelta(days=2),
                "effective_from": NOW - timedelta(days=1),
            }
            if active
            else {}
        ),
    )


def request_for(policy):
    portfolio_id = uuid4()
    instrument_id = uuid4()
    return AnalysisRequest(
        instrument_id=instrument_id,
        portfolio_id=portfolio_id,
        portfolio=PortfolioView(
            portfolio_id, "合成版本组合", "CNY", Decimal("10000"), "ACTIVE", ()
        ),
        as_of=NOW,
        policy_version_label=policy.label,
        evidence=(),
        governance=freeze_governance(policy),
        input_snapshot_hash="a" * 64,
        thesis=AnalysisThesisInput(instrument_id=instrument_id, as_of=NOW),
    )


def test_governance_roundtrip_preserves_hash_and_keeps_test_formula_unapproved():
    request = request_for(frozen_policy(active=True))
    plan = request.governance
    assert not plan.allows_new_exposure and plan.formula.status == "TEST_DEFAULT"
    assert plan.strategy_status == "NOT_CONFIGURED"
    parsed = AnalysisWorkItem.model_validate_json(
        AnalysisWorkItem(request=request).model_dump_json()
    )
    assert parsed.request.governance == plan
    assert parsed.request.governance.content_hash == plan.content_hash
    assert parsed.request.input_snapshot_hash == request.input_snapshot_hash
    assert plan.snapshot()["policy"]["config"]["entry"]["require_thesis_states"] == [
        "STRENGTHENING",
        "VALID",
    ]


def test_governance_hash_is_stable_across_worker_process_hash_seeds():
    plan = freeze_governance(frozen_policy())
    script = (
        "import sys; "
        "from investment_os.application.analysis_governance import AnalysisGovernancePlan; "
        "print(AnalysisGovernancePlan.model_validate_json(sys.stdin.read()).content_hash)"
    )
    for seed in ("1", "2"):
        result = subprocess.run(
            [sys.executable, "-c", script],
            input=plan.model_dump_json(),
            text=True,
            capture_output=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        assert result.stdout.strip() == plan.content_hash


@pytest.mark.parametrize(
    "change",
    [
        "missing_approval",
        "nonhuman",
        "missing_time",
        "naive",
        "backdated",
        "wrong_hash",
        "test_identity",
        "unsafe_reason",
    ],
)
def test_invalid_governance_policy_is_rejected(change):
    source = frozen_policy(active=change != "test_identity")
    payload = json.loads(source.model_dump_json())
    if change == "missing_approval":
        payload["approved_by"] = ""
    elif change == "nonhuman":
        payload["approved_by_actor"] = "AGENT"
    elif change == "missing_time":
        payload["approved_at"] = None
    elif change == "naive":
        payload["effective_from"] = "2026-10-20T08:00:00"
    elif change == "backdated":
        payload["effective_from"] = (NOW - timedelta(days=3)).isoformat()
    elif change == "wrong_hash":
        payload["content_hash"] = "b" * 64
    elif change == "test_identity":
        payload["policy_version_id"] = str(uuid4())
    elif change == "unsafe_reason":
        payload["config"]["behavior"]["reason_required_for_every_action"] = False
        config = InvestmentPolicySchema.model_validate_json(json.dumps(payload["config"]))
        payload["content_hash"] = policy_config_hash(config)
    with pytest.raises(ValidationError):
        FrozenAnalysisPolicy.model_validate_json(json.dumps(payload))


def test_policy_not_effective_or_naive_analysis_time_is_rejected():
    policy = frozen_policy(active=True)
    for as_of in (NOW - timedelta(days=5), NOW.replace(tzinfo=None)):
        with pytest.raises(ValueError, match="analysis time"):
            policy.require_available(as_of)


async def test_prepared_run_without_snapshot_or_after_prompt_or_formula_change_never_calls_model(
    monkeypatch,
):
    request = request_for(frozen_policy())
    service = ProductAnalysisService(
        inputs=None, portfolios=None, analysis_runs=None, committee=None, market_data=None
    )
    calls = []

    async def execute(*args, **kwargs):
        calls.append(args)
        return AnalysisRunResult("FAILED", None, "SYNTHETIC", "合成失败")

    monkeypatch.setattr("investment_os.application.analysis_product.execute_analysis", execute)
    missing = await service.execute_prepared(replace(request, governance=None))
    assert missing.failure_code == "ANALYSIS_GOVERNANCE_SNAPSHOT_MISSING"
    for name, value in (
        ("_AGENT_OPINION_SCHEMA_INSTRUCTION", "different synthetic instruction"),
        ("DEFAULT_SIZING_FORMULA", replace(DEFAULT_SIZING_FORMULA, version="synthetic-next")),
    ):
        with monkeypatch.context() as patch:
            patch.setattr(f"investment_os.application.analysis_orchestrator.{name}", value)
            result = await service.execute_prepared(request)
            assert result.failure_code == "ANALYSIS_GOVERNANCE_CHANGED"
    assert calls == []
    assert (await service.execute_prepared(request)).failure_code == "SYNTHETIC"
    assert len(calls) == 1


def test_prompt_hash_tracks_actual_instruction_not_just_version_label(monkeypatch):
    before = _prompt_hash(AgentRole.MACRO)
    monkeypatch.setattr(
        "investment_os.application.analysis_orchestrator._AGENT_OPINION_SCHEMA_INSTRUCTION",
        "synthetic changed text",
    )
    assert _prompt_hash(AgentRole.MACRO) != before
    assert _prompt_hash(AgentRole.MACRO) != _prompt_hash(AgentRole.INDUSTRY)


async def test_sizing_receives_frozen_policy_limits_not_test_default_constants(monkeypatch):
    request = request_for(frozen_policy(active=True, cap="2"))
    market = InMemoryMarketDataAdapter()
    market.put(
        MarketQuote(
            request.instrument_id,
            Decimal("10"),
            "CNY",
            NOW,
            "SYNTHETIC",
            volatility=Decimal("0.20"),
        )
    )
    import investment_os.application.analysis_orchestrator as orchestrator

    original = orchestrator.size_position
    seen = []

    def capture(formula, sizing_request):
        seen.append(sizing_request.policy.single_instrument_max.value)
        return original(formula, sizing_request)

    monkeypatch.setattr(orchestrator, "size_position", capture)
    valuation, sizing, failures = await _build_valuation_and_sizing(
        request=request,
        market_data=market,
        proposed=Action.BUY,
        risk_intent=RiskIntent.NORMAL,
        assessment=RiskAssessment(
            uuid4(),
            1,
            UtcTimestamp(NOW),
            UtcTimestamp(NOW + timedelta(hours=1)),
            (
                RiskFlag(
                    "SYNTHETIC", RiskFlagKind.SOFT, RiskSeverity.LOW, (uuid4(),), "合成解除条件"
                ),
            ),
        ),
        thesis_state=ThesisState.VALID,
    )
    assert valuation["status"] == "OK" and failures == []
    assert seen == [Decimal("0.02")]
    assert sizing["target_weight"] == "0.02"
    assert sizing["policy_version_id"] == str(request.governance.policy.policy_version_id)
    assert sizing["policy_content_hash"] == request.governance.policy.content_hash
    assert not request.governance.allows_new_exposure
