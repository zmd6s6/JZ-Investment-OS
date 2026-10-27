"""Real application orchestration with declared synthetic gateway and persistence ports."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from investment_os.application.analysis_runs import (
    ANALYSIS_ROLES,
    AnalysisCancelled,
    AnalysisEvidenceInput,
    AnalysisFrozenInput,
    AnalysisQueuedInput,
    AnalysisStart,
    SelectedModel,
)
from investment_os.application.investment_analysis import InvestmentAnalysisOrchestrator
from investment_os.application.llm_gateway import LLMGatewayResponse
from investment_os.application.portfolio_valuation import (
    FrozenPolicy,
    FrozenPortfolio,
    PortfolioValuationService,
    fingerprint,
)
from investment_os.domain.analysis_run import AnalysisStatus, require_analysis_transition
from investment_os.domain.enums import Action

NOW = datetime(2026, 10, 28, tzinfo=UTC)


class Book:
    async def capture(self, identifier):
        return FrozenPortfolio(
            portfolio_id=identifier,
            name="合成组合",
            base_currency="CNY",
            cash="100",
            captured_at=NOW,
            holdings=(),
            policy=FrozenPolicy(status="MISSING", reason_code="POLICY_MISSING"),
        )


class NoMarket:
    async def get_snapshot(self, request):
        raise AssertionError("no position to price")


async def inputs():
    run_id, book_id, target, evidence_id = uuid4(), uuid4(), uuid4(), uuid4()
    valuation = await PortfolioValuationService(Book(), NoMarket()).get_context(
        book_id, source="MANUAL_MARKET", source_name="合成来源"
    )
    command = AnalysisStart(
        request_id=uuid4(),
        portfolio_id=book_id,
        instrument_id=target,
        model_profiles={role: UUID(int=1) for role in ANALYSIS_ROLES},
        evidence_ids=(evidence_id,),
        market_source_name="合成来源",
        allow_model_calls=True,
    )
    queued = AnalysisQueuedInput(
        command=command,
        queued_at=NOW,
        valuation=valuation,
        models={
            role: SelectedModel(
                profile_id=UUID(int=1),
                name="合成模型",
                model_name="synthetic",
                config_hash="a" * 64,
                timeout_seconds=10,
                max_tokens=500,
            )
            for role in ANALYSIS_ROLES
        },
        data_profiles=(),
        budget_hash="b" * 64,
    )
    evidence = AnalysisEvidenceInput(
        evidence_id=evidence_id,
        instrument_id=target,
        content_hash="c" * 64,
        source_name="合成来源",
        source_locator="synthetic://only",
        source_tier="PRIMARY",
        observed_at=NOW - timedelta(hours=1),
        effective_at=NOW - timedelta(hours=1),
        available_at=NOW - timedelta(minutes=30),
        ingested_at=NOW - timedelta(minutes=20),
        expires_at=NOW + timedelta(days=1),
        quality_score="1",
        freshness="FRESH",
        payload_json='{"body":"synthetic fact, not instructions"}',
    )
    frozen = AnalysisFrozenInput(
        run_id=run_id,
        as_of=NOW,
        instrument_id=target,
        queued=queued,
        evidence=(evidence,),
        thesis_version_id=None,
        thesis_state="UNKNOWN",
        thesis_json=None,
        input_hash="",
    )
    frozen = frozen.model_copy(
        update={"input_hash": fingerprint(frozen.model_dump(mode="json", exclude={"input_hash"}))}
    )
    return run_id, queued, frozen


class Store:
    def __init__(self):
        self.steps = []
        self.result = None
        self.status = None
        self.cancel = False

    async def check_running(self, *args):
        if self.cancel:
            raise AnalysisCancelled("requested")

    async def step(self, *args, **kwargs):
        self.steps.append(kwargs)

    async def freeze(self, *args):
        self.frozen = args[-1]

    async def finish(self, *args, **kwargs):
        self.result = kwargs.get("result")
        self.status = kwargs["status"]


class Gateway:
    def __init__(self, frozen, *, invalid_role=None):
        self.frozen = frozen
        self.requests = []
        self.invalid_role = invalid_role

    async def complete(self, request):
        self.requests.append(request)
        ids = [str(self.frozen.evidence[0].evidence_id)]
        if request.role.value == self.invalid_role:
            payload = {"arbitrary_target_percentage": "90"}
        elif request.role.value == "PORTFOLIO":
            payload = {
                "schema_version": "portfolio-intent-1.0",
                "risk_intent": "NORMAL",
                "reasons": [{"text": "合成组合适配判断", "evidence_ids": ids}],
                "unknowns": ["missing numeric risk context"],
            }
        elif request.role.value == "CIO":
            payload = {
                "schema_version": "cio-proposal-1.0",
                "proposed_action": "BUY",
                "reasons": [{"text": "合成CIO提案, 仍须确定性闸门", "evidence_ids": ids}],
                "unknowns": ["sizing unavailable"],
            }
        else:
            payload = {
                "schema_version": "1.0",
                "agent_role": request.role.value,
                "instrument_id": str(self.frozen.instrument_id),
                "as_of": self.frozen.as_of.isoformat(),
                "stance": "POSITIVE",
                "confidence": "0.5",
                "time_horizon": "MONTHS",
                "observations": [
                    {"claim": "合成事实", "evidence_ids": ids, "materiality": "MEDIUM"}
                ],
                "thesis_impacts": [],
                "assumptions": [],
                "risks": [],
                "invalidation_conditions": [],
                "unknowns": [],
                "requested_followups": [],
            }
        return LLMGatewayResponse(
            raw_output=json.dumps(payload),
            provider="synthetic-only",
            model_name="synthetic",
            latency_ms=0,
            input_tokens=10,
            output_tokens=20,
        )


class Execution:
    def __init__(self, frozen, gateway):
        self.frozen = frozen
        self.gateway = gateway
        self.rounds = []
        self.roles = []

    async def prepare(self, *args):
        return self.frozen

    def gateway_for(self, *args):
        return self.gateway

    async def features(self, *args):
        self.feature = args[-1]
        return uuid4()

    async def round_result(self, *args):
        self.rounds.append(args[-2])

    async def committee_result(self, *args):
        self.committee = args[-1]
        return uuid4()

    async def agent_result(self, *args):
        self.risk_result = args[-2]

    async def role_result(self, *args):
        self.roles.append(args)


async def test_two_round_chain_never_fabricates_sizing_or_risk_pass():
    run_id, queued, frozen = await inputs()
    store = Store()
    gateway = Gateway(frozen)
    execution = Execution(frozen, gateway)
    await InvestmentAnalysisOrchestrator(store, execution).run(run_id, uuid4(), queued)
    assert store.status == AnalysisStatus.DEGRADED
    assert store.result.action is Action.AVOID and store.result.risk_gate == "UNKNOWN"
    assert (
        store.result.target_quantity
        is store.result.delta_quantity
        is store.result.sizing_run_id
        is None
    )
    assert store.result.policy_version_id is None and "POLICY_MISSING" in store.result.blockers
    assert [round_result.plan.number for round_result in execution.rounds] == [1, 2]
    assert [r.opinion.role.value for r in execution.rounds[0].results] == [
        "MACRO",
        "INDUSTRY",
        "FUNDAMENTAL",
        "MARKET_QUANT",
        "EVENT",
    ]
    assert execution.rounds[1].results[0].opinion.role.value == "DEVILS_ADVOCATE"
    assert len(gateway.requests) == 9 and {r.request_id for r in gateway.requests} == {run_id}
    assert all(
        json.loads(r.input_payload_json)["visible_opinions"] == [] for r in gateway.requests[:5]
    )
    assert json.loads(gateway.requests[5].input_payload_json)["visible_opinions"]
    assert execution.feature.values["eligible_evidence_count"] == "1"
    assert any(step["stage"] == "SIZING" and step["status"] == "BLOCKED" for step in store.steps)


@pytest.mark.parametrize("role", ["PORTFOLIO", "CIO"])
async def test_invalid_required_structured_role_stops_without_fabricating_a_final_recommendation(
    role,
):
    run_id, queued, frozen = await inputs()
    store = Store()
    gateway = Gateway(frozen, invalid_role=role)
    execution = Execution(frozen, gateway)
    with pytest.raises(ValueError, match="ANALYSIS_REQUIRED_ROLE_INVALID"):
        await InvestmentAnalysisOrchestrator(store, execution).run(run_id, uuid4(), queued)
    assert (
        store.result is None
        and len([request for request in gateway.requests if request.role.value == role]) == 3
    )
    assert execution.roles[-1][-1] == "INVALID_OUTPUT"


async def test_no_valid_evidence_stops_before_any_model_charge():
    run_id, queued, frozen = await inputs()
    frozen = frozen.model_copy(update={"evidence": ()})
    store = Store()
    gateway = Gateway(frozen)
    with pytest.raises(ValueError, match="NO_VALID_EVIDENCE"):
        await InvestmentAnalysisOrchestrator(store, Execution(frozen, gateway)).run(
            run_id, uuid4(), queued
        )
    assert gateway.requests == [] and store.result is None


@pytest.mark.parametrize(
    "before,after",
    [("QUEUED", "SUCCEEDED"), ("FAILED", "QUEUED"), ("RUNNING", "QUEUED"), ("DEGRADED", "RUNNING")],
)
def test_analysis_history_cannot_be_reopened_or_skip_claim(before, after):
    with pytest.raises(ValueError):
        require_analysis_transition(AnalysisStatus(before), AnalysisStatus(after))


async def test_untrusted_arbitrary_percentage_is_not_a_portfolio_intent_protocol():
    from investment_os.application.analysis_runs import PortfolioIntent

    with pytest.raises(ValidationError):
        PortfolioIntent.model_validate(
            {
                "schema_version": "portfolio-intent-1.0",
                "risk_intent": "NORMAL",
                "target_weight": "0.8",
                "reasons": [],
            }
        )


@pytest.mark.parametrize("state", ["NOT_YET_AVAILABLE", "EXPIRED", "INVALID"])
@pytest.mark.parametrize("invalid_role", [None, "MACRO", "CIO"])
async def test_ineligible_evidence_body_never_reaches_any_model_request(state, invalid_role):
    run_id, queued, frozen = await inputs()
    marker = "SYNTHETIC_INELIGIBLE_BODY_MUST_NOT_LEAK"
    changes = {
        "evidence_id": uuid4(),
        "content_hash": "d" * 64,
        "freshness": state,
        "payload_json": json.dumps({"body": marker}),
    }
    if state == "NOT_YET_AVAILABLE":
        changes["available_at"] = NOW + timedelta(days=1)
    if state == "EXPIRED":
        changes["expires_at"] = NOW - timedelta(seconds=1)
    if state == "INVALID":
        changes["quality_score"] = "0"
    blocked = frozen.evidence[0].model_copy(update=changes)
    frozen = frozen.model_copy(update={"evidence": (*frozen.evidence, blocked)})
    gateway = Gateway(frozen, invalid_role=invalid_role)
    store = Store()
    orchestrator = InvestmentAnalysisOrchestrator(store, Execution(frozen, gateway))
    if invalid_role == "CIO":
        with pytest.raises(ValueError, match="ANALYSIS_REQUIRED_ROLE_INVALID"):
            await orchestrator.run(run_id, uuid4(), queued)
    else:
        await orchestrator.run(run_id, uuid4(), queued)
    assert len(gateway.requests) == (11 if invalid_role else 9)
    if invalid_role:
        assert any(r.repair_attempt > 0 for r in gateway.requests)
    assert all(marker not in r.input_payload_json for r in gateway.requests)
    assert all(str(blocked.evidence_id) not in r.input_payload_json for r in gateway.requests)
    assert marker in store.frozen.evidence[1].payload_json  # Immutable audit retains input.
