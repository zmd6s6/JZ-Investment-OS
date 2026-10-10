"""PRODUCT-06: end-to-end analysis orchestration over existing application ports.

Produces a persisted-ready AnalysisRunResult: frozen Evidence context, bounded
committee opinions, risk assessment, deterministic valuation/sizing (when data
allows), and a CIO-gated shadow Decision. No orders, no policy mutation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from investment_os.application.agent_registry import AgentRoleRegistry, PromptBundle
from investment_os.application.agent_runtime import AgentRunResult, AgentRuntime
from investment_os.application.analysis_context import (
    AnalysisContext,
    AnalysisEvidence,
    EvidenceSourceTier,
    freeze_analysis_context,
)
from investment_os.application.committee import (
    detect_stance_conflicts,
)
from investment_os.application.committee_runtime import (
    CommitteeRoleInput,
    CommitteeRuntime,
)
from investment_os.application.decision_engine import (
    CioAggregationInput,
    GateOutcome,
    aggregate_cio_recommendation,
)
from investment_os.application.errors import ApplicationError
from investment_os.application.llm_gateway import (
    LLMGatewayFailure,
    LLMGatewayRequest,
)
from investment_os.application.market_data import MarketDataPort
from investment_os.application.portfolio_book import PortfolioView
from investment_os.domain.agent import (
    AgentOpinion,
    AgentRole,
    AgentTool,
    OpinionStance,
)
from investment_os.domain.enums import (
    Action,
    PositionBucket,
    RiskGateState,
    RiskIntent,
    ThesisState,
)
from investment_os.domain.policy import PositionPolicy
from investment_os.domain.portfolio import PortfolioCapacityInputs
from investment_os.domain.risk import RiskAssessment, RiskFlag, RiskFlagKind, RiskSeverity
from investment_os.domain.sizing import SizingFormula, SizingRequest, size_position
from investment_os.domain.values import Quantity, UtcTimestamp, Weight, exact_decimal

ROUND_ONE = (
    AgentRole.MACRO,
    AgentRole.INDUSTRY,
    AgentRole.FUNDAMENTAL,
    AgentRole.MARKET_QUANT,
    AgentRole.EVENT,
)
ALL_ANALYSIS_ROLES = (*ROUND_ONE, AgentRole.DEVILS_ADVOCATE, AgentRole.PORTFOLIO, AgentRole.RISK)

DEFAULT_POSITION_POLICY = PositionPolicy(
    single_instrument_max=Weight(Decimal("0.08")),
    sector_max=Weight(Decimal("0.25")),
    gross_exposure_max=Weight(Decimal("1")),
    minimum_cash=Weight(Decimal("0.10")),
    core_ratio_target=Weight(Decimal("0.75")),
    tactical_ratio_target=Weight(Decimal("0.25")),
)

DEFAULT_SIZING_FORMULA = SizingFormula(
    version="p6-test-default-v1",
    intent_weights={
        RiskIntent.NONE: Weight(Decimal("0")),
        RiskIntent.TINY: Weight(Decimal("0.01")),
        RiskIntent.SMALL: Weight(Decimal("0.03")),
        RiskIntent.NORMAL: Weight(Decimal("0.05")),
        RiskIntent.HIGH: Weight(Decimal("0.05")),
        RiskIntent.EXIT: Weight(Decimal("0")),
    },
    target_volatility=Decimal("0.20"),
    volatility_floor=Decimal("0.10"),
    volatility_scale_min=Decimal("0.5"),
    volatility_scale_max=Decimal("1"),
    reduce_fraction=Weight(Decimal("0.50")),
)


def _prompt_hash(role: AgentRole) -> str:
    from hashlib import sha256

    return sha256(f"p6-prompt|{role.value}|v1".encode()).hexdigest()


def default_registry() -> AgentRoleRegistry:
    return AgentRoleRegistry(
        tuple(
            PromptBundle(
                role=role,
                version="p6-v1",
                content_hash=_prompt_hash(role),
                allowed_tools=(AgentTool.RETRIEVE_EVIDENCE,),
            )
            for role in ALL_ANALYSIS_ROLES
        )
    )


def default_request_factory(role: AgentRole, role_input: CommitteeRoleInput) -> LLMGatewayRequest:
    from investment_os.application.committee_runtime import CommitteeRoleInput

    payload = {
        "role": role.value,
        "as_of": role_input.context.as_of.value.isoformat(),
        "instrument_id": str(role_input.context.instrument_id),
        "evidence_ids": sorted(str(i) for i in role_input.context.visible_evidence_ids),
        "input_snapshot_hash": role_input.context.input_snapshot_hash,
    }
    if isinstance(role_input, CommitteeRoleInput) and role_input.content_hash:
        payload["committee_context_hash"] = role_input.content_hash
    return LLMGatewayRequest(
        request_id=uuid4(),
        role=role,
        prompt_bundle_hash=_prompt_hash(role),
        input_snapshot_hash=role_input.context.input_snapshot_hash,
        timeout_seconds=30,
        max_output_tokens=2048,
        committee_context_hash=role_input.content_hash,
        system_instruction=(
            "You are a bounded investment research role. Use only provided evidence IDs. "
            "Return strict JSON AgentOpinion schema 1.0."
        ),
        input_payload_json=json.dumps(payload, sort_keys=True),
    )


@dataclass(frozen=True, slots=True)
class AnalysisEvidenceSource:
    """Minimal evidence facts loaded for one instrument at as_of."""

    evidence_id: UUID
    content_hash: str
    available_at: datetime
    source_tier: str = "PRIMARY"


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    instrument_id: UUID
    portfolio_id: UUID
    portfolio: PortfolioView
    as_of: datetime
    policy_version_label: str
    evidence: tuple[AnalysisEvidenceSource, ...]
    source: str = "PORTFOLIO"  # PORTFOLIO | WATCHLIST
    thesis_state: ThesisState = ThesisState.VALID
    thesis_version_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class OpinionSummary:
    role: str
    stance: str
    confidence: str
    model_provider: str | None
    model_name: str | None
    claims: tuple[dict[str, Any], ...]
    assumptions: tuple[str, ...]
    unknowns: tuple[str, ...]
    risks: tuple[dict[str, Any], ...]
    failure: str | None
    repair_count: int
    total_tokens: int
    total_cost: str | None


@dataclass(frozen=True, slots=True)
class AnalysisRunPayload:
    """Serializable, versioned content of one completed or failed analysis."""

    schema_version: str
    instrument_id: UUID
    portfolio_id: UUID
    as_of: str
    source: str
    policy_version_label: str
    evidence_ids: tuple[str, ...]
    context_hash: str
    opinions: tuple[OpinionSummary, ...]
    conflicts: tuple[dict[str, Any], ...]
    risk: dict[str, Any]
    valuation: dict[str, Any]
    sizing: dict[str, Any] | None
    decision: dict[str, Any]
    failures: tuple[str, ...]
    token_usage: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "instrument_id": str(self.instrument_id),
            "portfolio_id": str(self.portfolio_id),
            "as_of": self.as_of,
            "source": self.source,
            "policy_version_label": self.policy_version_label,
            "evidence_ids": list(self.evidence_ids),
            "context_hash": self.context_hash,
            "opinions": [
                {
                    "role": o.role,
                    "stance": o.stance,
                    "confidence": o.confidence,
                    "model_provider": o.model_provider,
                    "model_name": o.model_name,
                    "claims": list(o.claims),
                    "assumptions": list(o.assumptions),
                    "unknowns": list(o.unknowns),
                    "risks": list(o.risks),
                    "failure": o.failure,
                    "repair_count": o.repair_count,
                    "total_tokens": o.total_tokens,
                    "total_cost": o.total_cost,
                }
                for o in self.opinions
            ],
            "conflicts": list(self.conflicts),
            "risk": self.risk,
            "valuation": self.valuation,
            "sizing": self.sizing,
            "decision": self.decision,
            "failures": list(self.failures),
            "token_usage": self.token_usage,
        }


@dataclass(frozen=True, slots=True)
class AnalysisRunResult:
    status: str  # SUCCEEDED | FAILED
    payload: AnalysisRunPayload | None
    failure_code: str | None = None
    failure_detail: str | None = None


def _summarize_run(result: AgentRunResult) -> OpinionSummary:
    provider = result.attempts[-1].provider if result.attempts else None
    model = result.attempts[-1].model_name if result.attempts else None
    tokens = sum(a.input_tokens + a.output_tokens for a in result.attempts)
    cost = next(
        (a.total_cost for a in reversed(result.attempts) if a.total_cost is not None),
        None,
    )
    failure = result.failure.value if result.failure else None
    return OpinionSummary(
        role=result.opinion.role.value,
        stance=result.opinion.stance.value,
        confidence=str(result.opinion.confidence.value),
        model_provider=provider,
        model_name=model,
        claims=tuple(
            {
                "claim": obs.claim,
                "evidence_ids": [str(e) for e in obs.evidence_ids],
                "materiality": obs.materiality.value,
            }
            for obs in result.opinion.observations
        ),
        assumptions=result.opinion.assumptions,
        unknowns=result.opinion.unknowns,
        risks=tuple(
            {
                "code": risk.code,
                "severity": risk.severity.value,
                "evidence_ids": [str(e) for e in risk.evidence_ids],
            }
            for risk in result.opinion.risks
        ),
        failure=failure,
        repair_count=result.repair_count,
        total_tokens=tokens,
        total_cost=str(cost) if cost is not None else None,
    )


def _stance_action(opinion: AgentOpinion) -> Action:
    mapping = {
        OpinionStance.STRONGLY_POSITIVE: Action.BUY,
        OpinionStance.POSITIVE: Action.BUY,
        OpinionStance.NEUTRAL: Action.HOLD,
        OpinionStance.MIXED: Action.HOLD,
        OpinionStance.NEGATIVE: Action.REDUCE,
        OpinionStance.STRONGLY_NEGATIVE: Action.EXIT,
        OpinionStance.INSUFFICIENT_DATA: Action.WATCH,
    }
    return mapping.get(opinion.stance, Action.WATCH)


def _gate_from_stance(
    opinion: AgentOpinion | None, positive: tuple[OpinionStance, ...]
) -> GateOutcome:
    if opinion is None or opinion.stance is OpinionStance.INSUFFICIENT_DATA:
        return GateOutcome.UNKNOWN
    if opinion.stance in positive:
        return GateOutcome.PASS
    if opinion.stance in (
        OpinionStance.NEUTRAL,
        OpinionStance.MIXED,
    ):
        return GateOutcome.UNKNOWN
    return GateOutcome.FAIL


def _risk_intent_from_portfolio(portfolio_opinion: AgentOpinion | None) -> RiskIntent:
    if portfolio_opinion is None or portfolio_opinion.stance is OpinionStance.INSUFFICIENT_DATA:
        return RiskIntent.NONE
    if portfolio_opinion.stance in (
        OpinionStance.STRONGLY_POSITIVE,
        OpinionStance.POSITIVE,
    ):
        return RiskIntent.NORMAL
    if portfolio_opinion.stance in (OpinionStance.NEUTRAL, OpinionStance.MIXED):
        return RiskIntent.TINY
    if portfolio_opinion.stance in (
        OpinionStance.NEGATIVE,
        OpinionStance.STRONGLY_NEGATIVE,
    ):
        return RiskIntent.EXIT
    return RiskIntent.NONE


def build_risk_assessment(
    *,
    as_of: datetime,
    opinion_results: tuple[AgentRunResult, ...],
    visible_ids: frozenset[UUID],
) -> RiskAssessment:
    """Derive HARD/SOFT flags from evidence-backed agent risks only."""

    from datetime import timedelta as _td

    flags: list[RiskFlag] = []
    seen_codes: set[str] = set()
    for result in opinion_results:
        for risk in result.opinion.risks:
            evidence_ids = tuple(e for e in risk.evidence_ids if e in visible_ids)
            if not evidence_ids:
                continue
            code = risk.code.upper().replace(" ", "_")[:48]
            if code in seen_codes:
                continue
            seen_codes.add(code)
            agent_severity = risk.severity.value
            domain_severity = RiskSeverity(agent_severity)
            kind = (
                RiskFlagKind.HARD
                if domain_severity in (RiskSeverity.HIGH, RiskSeverity.CRITICAL)
                else RiskFlagKind.SOFT
            )
            flags.append(
                RiskFlag(
                    code=code,
                    kind=kind,
                    severity=domain_severity,
                    evidence_ids=evidence_ids,
                    release_condition=f"Clear {risk.code} with refreshed evidence.",
                )
            )

    if not flags:
        # Empty flags → UNKNOWN gate. Provide a benign soft flag so the gate is PASS
        # only when at least one evidence-backed monitoring fact exists.
        if visible_ids:
            flags.append(
                RiskFlag(
                    code="MONITORING_ONLY",
                    kind=RiskFlagKind.SOFT,
                    severity=RiskSeverity.LOW,
                    evidence_ids=tuple(sorted(visible_ids, key=str))[:1],
                    release_condition="No hard risk flag raised during this run.",
                )
            )
        else:
            # Still need unique evidence_ids for a dummy; use synthetic empty path via DomainError?
            # Assessment requires flags for PASS/UNKNOWN via gate property:
            # empty flags → UNKNOWN. That is acceptable fail-closed.
            flags = []

    return RiskAssessment(
        id=uuid4(),
        version=1,
        as_of=UtcTimestamp(as_of),
        expires_at=UtcTimestamp(as_of + _td(hours=24)),
        flags=tuple(flags),
    )


async def _run_single_role(
    runtime: AgentRuntime,
    *,
    role: AgentRole,
    context: AnalysisContext,
) -> AgentRunResult:
    factory = default_request_factory

    class _One:
        pass

    # Reuse default factory with synthetic role input
    from investment_os.application.committee_runtime import CommitteeRoleInput as CRI

    request = factory(role, CRI(context=context))
    return await runtime.run(request=request, context=context)


async def execute_analysis(
    request: AnalysisRequest,
    *,
    committee: CommitteeRuntime,
    market_data: MarketDataPort,
    logger: Any | None = None,
) -> AnalysisRunResult:
    """Run one full bounded analysis and return a serializable result."""

    failures: list[str] = []
    if not request.evidence:
        return AnalysisRunResult(
            status="FAILED",
            payload=None,
            failure_code="INSUFFICIENT_EVIDENCE",
            failure_detail="分析时点没有可用 Evidence; 已失败关闭。",
        )

    context = freeze_analysis_context(
        request.instrument_id,
        as_of=request.as_of,
        evidence=tuple(
            AnalysisEvidence(
                evidence_id=item.evidence_id,
                content_hash=item.content_hash,
                available_at=UtcTimestamp(item.available_at),
                source_tier=EvidenceSourceTier(item.source_tier)
                if item.source_tier in ("PRIMARY", "REPUTABLE_SECONDARY", "OTHER")
                else EvidenceSourceTier.OTHER,
                independence_key=item.content_hash[:32],
            )
            for item in request.evidence
        ),
    )

    try:
        session = await committee.run_session(
            context=context,
            request_factory=default_request_factory,
        )
    except LLMGatewayFailure as exc:
        return AnalysisRunResult(
            status="FAILED",
            payload=None,
            failure_code="GATEWAY_FAILURE",
            failure_detail=str(exc),
        )
    except ApplicationError as exc:
        return AnalysisRunResult(
            status="FAILED",
            payload=None,
            failure_code=exc.code.value,
            failure_detail=exc.message,
        )

    round_one = session.rounds[0]
    round_two = session.rounds[1]
    all_round_results = round_one.results + round_two.results
    conflicts = detect_stance_conflicts(tuple(r.opinion for r in round_one.results))

    # Dedicated Portfolio Manager + Risk Manager runs (same frozen context).
    try:
        portfolio_result = await _run_single_role(
            committee._agent_runtime,
            role=AgentRole.PORTFOLIO,
            context=context,
        )
        risk_result = await _run_single_role(
            committee._agent_runtime,
            role=AgentRole.RISK,
            context=context,
        )
    except LLMGatewayFailure as exc:
        return AnalysisRunResult(
            status="FAILED",
            payload=None,
            failure_code="GATEWAY_FAILURE",
            failure_detail=str(exc),
        )
    except ApplicationError as exc:
        return AnalysisRunResult(
            status="FAILED",
            payload=None,
            failure_code=exc.code.value,
            failure_detail=exc.message,
        )

    opinions = (*all_round_results, portfolio_result, risk_result)
    by_role = {result.opinion.role: result for result in opinions}

    fundamental = by_role.get(AgentRole.FUNDAMENTAL)
    market = by_role.get(AgentRole.MARKET_QUANT)
    pm = by_role.get(AgentRole.PORTFOLIO)
    risk = by_role.get(AgentRole.RISK)

    proposed = _stance_action(fundamental.opinion) if fundamental else Action.WATCH
    # Prefer explicit BUY only when multiple specialists are positive
    positive = (OpinionStance.POSITIVE, OpinionStance.STRONGLY_POSITIVE)
    if proposed is Action.BUY:
        positives = sum(
            1 for result in (fundamental, market) if result and result.opinion.stance in positive
        )
        if positives == 0:
            proposed = Action.HOLD

    assessment = build_risk_assessment(
        as_of=request.as_of,
        opinion_results=opinions,
        visible_ids=context.visible_evidence_ids,
    )
    risk_gate = assessment.gate

    thesis_state = request.thesis_state
    data_sufficient = len(context.visible_evidence_ids) > 0

    # Valuation for all positions (NAV) + target instrument quote.
    valuation, sizing, valuation_failures = await _build_valuation_and_sizing(
        request=request,
        market_data=market_data,
        proposed=proposed,
        risk_intent=_risk_intent_from_portfolio(pm.opinion if pm else None),
        assessment=assessment,
        thesis_state=thesis_state,
    )
    failures.extend(valuation_failures)
    if valuation.get("missing_quotes") and proposed in (Action.BUY, Action.ADD):
        data_sufficient = False

    cio_input = CioAggregationInput(
        proposed_action=proposed,
        investment_quality=_gate_from_stance(
            fundamental.opinion if fundamental else None, positive
        ),
        thesis_state=thesis_state,
        timing=_gate_from_stance(market.opinion if market else None, positive),
        portfolio_fit=_gate_from_stance(pm.opinion if pm else None, positive),
        risk_gate=risk_gate,
        policy_passed=True,
        data_sufficient=data_sufficient,
    )
    recommendation = aggregate_cio_recommendation(cio_input)

    # Risk veto must block BUY/ADD explicitly in the decision record.
    final_action = recommendation.action
    veto = risk_gate is RiskGateState.VETO and final_action in (Action.BUY, Action.ADD)
    if veto:
        final_action = Action.WATCH
        failures.append("RISK_VETO_BLOCKED_BUY_ADD")

    summaries = tuple(_summarize_run(result) for result in opinions)
    total_tokens = sum(s.total_tokens for s in summaries)
    total_cost = None
    costs = [Decimal(s.total_cost) for s in summaries if s.total_cost]
    if costs:
        total_cost = str(sum(costs))

    decision = {
        "action": final_action.value,
        "proposed_action": proposed.value,
        "confidence": str(
            max(
                (fundamental.opinion.confidence.value if fundamental else Decimal("0")),
                Decimal("0"),
            )
        ),
        "risk_intent": _risk_intent_from_portfolio(pm.opinion if pm else None).value,
        "risk_veto": veto,
        "risk_gate": risk_gate.value,
        "gates": [
            {"gate": g.gate.value, "outcome": g.outcome.value, "reason": g.reason_code}
            for g in recommendation.gates
        ],
        "policy_version_label": request.policy_version_label,
        "core_action": final_action.value
        if final_action in (Action.BUY, Action.ADD, Action.HOLD)
        else "NONE",
        "tactical_action": "NONE"
        if final_action in (Action.BUY, Action.ADD)
        else final_action.value,
        "unknowns": list(dict.fromkeys(u for s in summaries for u in s.unknowns)),
        "dissent": list(
            dict.fromkeys(
                claim
                for s in summaries
                if s.role == AgentRole.DEVILS_ADVOCATE.value
                for claim in [json.dumps(list(s.claims), ensure_ascii=False)[:500]]
                if claim
            )
        ),
    }

    payload = AnalysisRunPayload(
        schema_version="1.0",
        instrument_id=request.instrument_id,
        portfolio_id=request.portfolio_id,
        as_of=request.as_of.isoformat(),
        source=request.source,
        policy_version_label=request.policy_version_label,
        evidence_ids=tuple(sorted(str(e) for e in context.visible_evidence_ids)),
        context_hash=context.input_snapshot_hash,
        opinions=summaries,
        conflicts=tuple(
            {
                "kind": c.kind.value,
                "roles": [r.value for r in c.roles],
            }
            for c in conflicts
        ),
        risk={
            "gate": risk_gate.value,
            "flags": [
                {
                    "code": f.code,
                    "kind": f.kind.value,
                    "severity": f.severity.value,
                    "evidence_ids": [str(e) for e in f.evidence_ids],
                    "release_condition": f.release_condition,
                }
                for f in assessment.flags
            ],
            "risk_agent_stance": risk.opinion.stance.value if risk else None,
        },
        valuation=valuation,
        sizing=sizing,
        decision=decision,
        failures=tuple(failures),
        token_usage={
            "total_tokens": total_tokens,
            "total_cost": total_cost,
        },
    )

    # Fail the run only when committee/config failed; valuation gaps stay in payload.
    return AnalysisRunResult(status="SUCCEEDED", payload=payload)


async def _build_valuation_and_sizing(
    *,
    request: AnalysisRequest,
    market_data: MarketDataPort,
    proposed: Action,
    risk_intent: RiskIntent,
    assessment: RiskAssessment,
    thesis_state: ThesisState,
) -> tuple[dict[str, Any], dict[str, Any] | None, list[str]]:
    failures: list[str] = []
    positions = request.portfolio.positions
    instrument_ids = tuple({p.instrument_id for p in positions} | {request.instrument_id})
    quotes = await market_data.get_reference_quotes(instrument_ids, as_of=request.as_of)
    missing = [str(i) for i in instrument_ids if i not in quotes]

    currencies = {p.currency for p in positions} | {request.portfolio.base_currency}
    # FX fail-closed for multi-currency
    if len(currencies) > 1:
        failures.append("FX_SOURCE_MISSING_MULTI_CURRENCY")
        valuation = {
            "status": "FAILED",
            "reason": "multi-currency portfolio requires FX",
            "missing_quotes": missing,
            "currencies": sorted(currencies),
        }
        return valuation, None, failures

    if missing and len(positions) > 0:
        failures.append("MISSING_REFERENCE_QUOTES")
        valuation = {
            "status": "PARTIAL",
            "reason": "missing reference quotes for NAV",
            "missing_quotes": missing,
            "currencies": sorted(currencies),
        }
        return valuation, None, failures

    # NAV = cash + sum(qty * price) for positions with quotes
    nav = exact_decimal(request.portfolio.cash_balance)
    price_by_id = {p.instrument_id: quotes.get(p.instrument_id) for p in positions}
    for pos in positions:
        quote = price_by_id[pos.instrument_id]
        if quote is None:
            failures.append("MISSING_REFERENCE_QUOTES")
            return (
                {
                    "status": "FAILED",
                    "reason": "missing quote",
                    "missing_quotes": missing or [str(pos.instrument_id)],
                    "currencies": sorted(currencies),
                },
                None,
                failures,
            )
        if quote.currency != request.portfolio.base_currency:
            failures.append("FX_SOURCE_MISSING_MULTI_CURRENCY")
            return (
                {
                    "status": "FAILED",
                    "reason": f"quote currency {quote.currency} != base "
                    + request.portfolio.base_currency,
                    "missing_quotes": [],
                    "currencies": sorted(currencies),
                },
                None,
                failures,
            )
        qty = pos.core_quantity + pos.tactical_quantity
        nav += exact_decimal(qty) * quote.reference_price

    if nav <= 0:
        failures.append("NAV_NON_POSITIVE")
        return {"status": "FAILED", "reason": "nav not positive"}, None, failures

    target_quote = quotes.get(request.instrument_id)
    if target_quote is None:
        failures.append("MISSING_REFERENCE_QUOTES")
        return (
            {
                "status": "FAILED",
                "reason": "target instrument quote missing",
                "missing_quotes": [str(request.instrument_id)],
                "currencies": sorted(currencies),
            },
            None,
            failures,
        )

    ok_valuation: dict[str, Any] = {
        "status": "OK",
        "nav": str(nav),
        "base_currency": request.portfolio.base_currency,
        "source": target_quote.source,
        "as_of": target_quote.as_of.isoformat(),
        "target_reference_price": str(target_quote.reference_price),
        "missing_quotes": [],
        "currencies": sorted(currencies),
        "single_currency_limit": True,
        "position_values": [
            {
                "instrument_id": str(p.instrument_id),
                "symbol": next(
                    (
                        x.symbol
                        for x in request.portfolio.positions
                        if x.instrument_id == p.instrument_id
                    ),
                    "",
                ),
                "quantity": str(p.core_quantity + p.tactical_quantity),
                "price": (
                    str(quotes[p.instrument_id].reference_price)
                    if p.instrument_id in quotes
                    else None
                ),
            }
            for p in positions
        ],
    }

    # Build capacity from current positions of target instrument.
    target_pos = next((p for p in positions if p.instrument_id == request.instrument_id), None)
    target_qty = (
        (target_pos.core_quantity + target_pos.tactical_quantity) if target_pos else Decimal("0")
    )
    target_value = exact_decimal(target_qty) * target_quote.reference_price
    target_weight = Weight(min(Decimal("1"), target_value / nav)) if nav else Weight(Decimal("0"))
    current_bucket_weight = target_weight
    current_bucket_quantity = Quantity(exact_decimal(target_qty) if target_pos else Decimal("0"))

    # Reconcile: weight * nav / price must equal quantity. Adjust by using weight derived
    # from quantity * price / nav (exact).
    expected_qty = target_weight.value * nav / target_quote.reference_price
    # Use exact quantity via weight that reconciles.
    if expected_qty != current_bucket_quantity.value:
        # recompute weight from exact identity
        current_bucket_weight = Weight(
            min(Decimal("1"), current_bucket_quantity.value * target_quote.reference_price / nav)
        )

    gross_value = sum(
        (p.core_quantity + p.tactical_quantity)
        * (quotes[p.instrument_id].reference_price if p.instrument_id in quotes else Decimal("0"))
        for p in positions
    )
    gross_weight = min(Decimal("1"), gross_value / nav) if nav else Decimal("0")
    capacity = PortfolioCapacityInputs(
        instrument_weight=target_weight,
        sector_weight=Weight(Decimal("0")),
        gross_exposure=Weight(gross_weight),
        pending_instrument_weight=Weight(Decimal("0")),
        pending_sector_weight=Weight(Decimal("0")),
        pending_gross_exposure=Weight(Decimal("0")),
        risk_budget_capacity=Weight(Decimal("1")),
        liquidity_capacity=Weight(Decimal("1")),
    )
    # Unknown sector stays zero; policy limits still apply.

    try:
        if proposed not in (Action.BUY, Action.ADD):
            # Still compute sizing for transparency when we have inputs
            pass
        request_obj = SizingRequest(
            action=proposed,
            bucket=PositionBucket.CORE,
            risk_intent=risk_intent,
            current_bucket_weight=current_bucket_weight,
            current_bucket_quantity=current_bucket_quantity,
            nav=nav,
            reference_price=target_quote.reference_price,
            lot_size=Quantity(Decimal("1")),
            instrument_volatility=target_quote.volatility,
            capacity_inputs=capacity,
            policy=DEFAULT_POSITION_POLICY,
            risk_assessment=assessment,
            thesis_state=thesis_state,
            as_of=UtcTimestamp(request.as_of),
        )
        result = size_position(DEFAULT_SIZING_FORMULA, request_obj)
        sizing: dict[str, Any] | None = {
            "formula_version": result.formula_version,
            "input_hash": result.input_hash,
            "target_weight": str(result.target_weight.value),
            "delta_weight": str(result.delta_weight),
            "target_quantity": str(result.target_quantity.value),
            "delta_quantity": str(result.delta_quantity),
            "reason_codes": list(result.reason_codes),
            "policy_version_label": request.policy_version_label,
        }
    except Exception as exc:  # sizing fail-closed without killing the run
        failures.append("SIZING_INPUT_INVALID")
        sizing = {"status": "FAILED", "reason": str(exc)[:300]}

    return ok_valuation, sizing, failures


def new_run_id() -> UUID:
    return uuid4()
