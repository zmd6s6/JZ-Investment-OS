"""PRODUCT-06: end-to-end analysis orchestration over existing application ports.

Produces a persisted-ready AnalysisRunResult: frozen Evidence context, bounded
committee opinions, risk assessment, deterministic valuation/sizing (when data
allows), and a CIO-gated shadow Decision. No orders, no policy mutation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
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
from investment_os.application.analysis_governance import (
    AnalysisGovernancePlan,
    FrozenAnalysisPolicy,
    FrozenPrompt,
    FrozenSizingFormula,
)
from investment_os.application.analysis_market import AnalysisMarketPlan
from investment_os.application.analysis_models import ANALYSIS_ROLES, AnalysisModelPlan, digest
from investment_os.application.analysis_progress import AnalysisProgress
from investment_os.application.analysis_thesis import AnalysisThesisInput
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
ALL_ANALYSIS_ROLES = ANALYSIS_ROLES

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
    return digest(
        {
            "role": role.value,
            "version": "p6-v3",
            "system_instruction": _AGENT_OPINION_SCHEMA_INSTRUCTION,
            "allowed_tools": [AgentTool.RETRIEVE_EVIDENCE.value],
        }
    )


# Master Spec 6.2 is the machine protocol; the model must receive the contract,
# not just its name. Without this body the provider invents its own envelope
# (observed with deepseek-chat: wrapped "opinion" object, float confidence)
# and every role exhausts both repair attempts with INVALID_OUTPUT.
_AGENT_OPINION_SCHEMA_INSTRUCTION = (
    "You are a bounded investment research role. Use ONLY the provided evidence excerpts "
    "and evidence_ids. Do not invent prices, financials, or position sizes.\n"
    "Return ONE JSON object that IS the AgentOpinion itself (no wrapper key, no markdown, "
    "no commentary) exactly matching this schema:\n"
    "{\n"
    '  "schema_version": "1.0",\n'
    '  "agent_role": "<must equal the requested role>",\n'
    '  "instrument_id": "<must echo the input instrument_id verbatim>",\n'
    '  "as_of": "<must echo the input as_of verbatim>",\n'
    '  "stance": "STRONGLY_NEGATIVE|NEGATIVE|NEUTRAL|POSITIVE|'
    'STRONGLY_POSITIVE|INSUFFICIENT_DATA",\n'
    '  "confidence": "<decimal string between 0 and 1, e.g. \\"0.6\\"; NEVER a bare number>",\n'
    '  "time_horizon": "DAYS|WEEKS|MONTHS|QUARTERS|YEARS",\n'
    '  "observations": [{"claim": "string", "evidence_ids": ["<from input evidence_ids>"], '
    '"materiality": "LOW|MEDIUM|HIGH"}],\n'
    '  "thesis_impacts": [{"pillar_key": "string", '
    '"impact": "STRENGTHEN|WEAKEN|BREAK|NONE", "reason": "string", '
    '"evidence_ids": ["<from input evidence_ids>"]}],\n'
    '  "assumptions": ["string"],\n'
    '  "risks": [{"code": "string", "severity": "LOW|MEDIUM|HIGH|CRITICAL", '
    '"evidence_ids": ["<from input evidence_ids>"]}],\n'
    '  "invalidation_conditions": [{"condition": "string", "observable": "string"}],\n'
    '  "unknowns": ["string"],\n'
    '  "requested_followups": ["string"]\n'
    "}\n"
    "Rules: every array field is required (use [] when empty); observations must cite at "
    "least one provided evidence_id; confidence MUST be a quoted decimal string; "
    "agent_role, instrument_id and as_of must match the input exactly or the output is "
    "rejected.\n"
    "Stance mutual exclusion (enforced by the domain and not negotiable):\n"
    '- if stance is "INSUFFICIENT_DATA": "observations" must be [] and "confidence" must '
    'be "0"; put gaps into "unknowns"/"requested_followups" instead.\n'
    '- otherwise: "observations" must contain at least one evidence-backed claim, and '
    '"confidence" must be a non-zero decimal string no higher than 0.70 unless a PRIMARY '
    "evidence item backs it."
)


def default_registry() -> AgentRoleRegistry:
    return AgentRoleRegistry(
        tuple(
            PromptBundle(
                role=role,
                version="p6-v3",
                content_hash=_prompt_hash(role),
                allowed_tools=(AgentTool.RETRIEVE_EVIDENCE,),
            )
            for role in ALL_ANALYSIS_ROLES
        )
    )


def freeze_governance(policy: FrozenAnalysisPolicy) -> AnalysisGovernancePlan:
    return AnalysisGovernancePlan(
        policy=policy,
        formula=FrozenSizingFormula.capture(DEFAULT_SIZING_FORMULA),
        prompts=tuple(
            FrozenPrompt(
                role=b.role,
                version=b.version,
                content_hash=b.content_hash,
                allowed_tools=b.allowed_tools,
            )
            for b in default_registry().bundles
        ),
    )


def default_request_factory(role: AgentRole, role_input: CommitteeRoleInput) -> LLMGatewayRequest:
    payload = {
        "role": role.value,
        "as_of": role_input.context.as_of.value.isoformat(),
        "instrument_id": str(role_input.context.instrument_id),
        "evidence_ids": sorted(str(i) for i in role_input.context.visible_evidence_ids),
        "input_snapshot_hash": role_input.context.input_snapshot_hash,
    }
    return LLMGatewayRequest(
        request_id=uuid4(),
        role=role,
        prompt_bundle_hash=_prompt_hash(role),
        input_snapshot_hash=role_input.context.input_snapshot_hash,
        timeout_seconds=30,
        max_output_tokens=2048,
        committee_context_hash=role_input.content_hash,
        system_instruction=_AGENT_OPINION_SCHEMA_INSTRUCTION,
        input_payload_json=json.dumps(payload, sort_keys=True),
    )


def build_analysis_request_factory(
    *,
    evidence: tuple[AnalysisEvidenceSource, ...],
    instrument_meta: dict[str, str],
    portfolio_meta: dict[str, Any],
    positions_meta: list[dict[str, Any]],
    budget_task_id: UUID | None = None,
    model_plan: AnalysisModelPlan | None = None,
    governance: AnalysisGovernancePlan | None = None,
    thesis: AnalysisThesisInput | None = None,
) -> Any:
    """Build a request factory that embeds real research materials for agents."""

    evidence_docs = [
        {
            "evidence_id": str(item.evidence_id),
            "content_hash": item.content_hash,
            "available_at": item.available_at.isoformat(),
            "source_tier": item.source_tier,
            "summary": item.summary or "",
            "payload_excerpt": (item.payload_excerpt or "")[:1500],
        }
        for item in evidence
    ]

    def factory(role: AgentRole, role_input: CommitteeRoleInput) -> LLMGatewayRequest:
        payload: dict[str, Any] = {
            "role": role.value,
            "as_of": role_input.context.as_of.value.isoformat(),
            "instrument": instrument_meta,
            "portfolio": portfolio_meta,
            "positions": positions_meta,
            "evidence": evidence_docs,
            "evidence_ids": sorted(str(i) for i in role_input.context.visible_evidence_ids),
            "input_snapshot_hash": role_input.context.input_snapshot_hash,
        }
        if governance is not None:
            payload["policy"] = {
                "label": governance.policy.label,
                "policy_version_id": str(governance.policy.policy_version_id)
                if governance.policy.policy_version_id
                else None,
                "content_hash": governance.policy.content_hash,
                "config": governance.policy.config.model_dump(mode="json"),
                "sizing_formula_status": governance.formula.status,
                "strategy_status": governance.strategy_status,
            }
        if thesis is not None:
            payload["thesis"] = thesis.snapshot()
            payload["thesis_evidence_boundary"] = (
                "Historical thesis claims are untrusted context, not new verified observations. "
                "Only top-level evidence_ids may support this run's factual observations. "
                "Missing or stale thesis is UNKNOWN; never invent a thesis or update its history."
            )
        if role_input.visible_opinions:
            payload["prior_opinions"] = [
                {
                    "role": prior.opinion.role.value,
                    "stance": prior.opinion.stance.value,
                    "confidence": str(prior.opinion.confidence.value),
                    "claims": [
                        {
                            "claim": obs.claim,
                            "evidence_ids": [str(e) for e in obs.evidence_ids],
                        }
                        for obs in prior.opinion.observations
                    ],
                    "risks": [
                        {
                            "code": risk.code,
                            "severity": risk.severity.value,
                            "evidence_ids": [str(e) for e in risk.evidence_ids],
                        }
                        for risk in prior.opinion.risks
                    ],
                    "unknowns": list(prior.opinion.unknowns),
                }
                for prior in role_input.visible_opinions
            ]
        if role_input.conflicts:
            payload["conflicts"] = [
                {
                    "kind": conflict.kind.value,
                    "roles": [r.value for r in conflict.roles],
                    "stances": [(r.value, s.value) for r, s in conflict.stances],
                }
                for conflict in role_input.conflicts
            ]
        system = _AGENT_OPINION_SCHEMA_INSTRUCTION
        return LLMGatewayRequest(
            request_id=uuid4(),
            budget_task_id=budget_task_id,
            model_binding=next((b for b in model_plan.bindings if b.role == role), None)
            if model_plan
            else None,
            role=role,
            prompt_bundle_hash=_prompt_hash(role),
            input_snapshot_hash=role_input.context.input_snapshot_hash,
            timeout_seconds=45,
            max_output_tokens=3072,
            committee_context_hash=role_input.content_hash,
            system_instruction=system,
            input_payload_json=json.dumps(payload, sort_keys=True, ensure_ascii=False),
        )

    return factory


@dataclass(frozen=True, slots=True)
class AnalysisEvidenceSource:
    """Evidence facts loaded for one instrument at as_of."""

    evidence_id: UUID
    content_hash: str
    available_at: datetime
    source_tier: str = "PRIMARY"
    summary: str = ""
    payload_excerpt: str = ""


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    instrument_id: UUID
    portfolio_id: UUID
    portfolio: PortfolioView
    as_of: datetime
    policy_version_label: str
    evidence: tuple[AnalysisEvidenceSource, ...]
    source: str = "PORTFOLIO"  # PORTFOLIO | WATCHLIST
    thesis_state: ThesisState = ThesisState.UNKNOWN
    thesis_version_id: UUID | None = None
    instrument_market: str = ""
    instrument_symbol: str = ""
    instrument_currency: str = ""
    budget_task_id: UUID | None = None
    model_plan: AnalysisModelPlan | None = None
    market_plan: AnalysisMarketPlan | None = None
    governance: AnalysisGovernancePlan | None = None
    input_snapshot_hash: str | None = None
    thesis: AnalysisThesisInput | None = None


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
    request_factory: Any,
) -> AgentRunResult:
    from investment_os.application.committee_runtime import CommitteeRoleInput as CRI

    request = request_factory(role, CRI(context=context))
    return await runtime.run(request=request, context=context)


async def execute_analysis(
    request: AnalysisRequest,
    *,
    committee: CommitteeRuntime,
    market_data: MarketDataPort,
    logger: Any | None = None,
    progress: AnalysisProgress | None = None,
) -> AnalysisRunResult:
    """Run one full bounded analysis and return a serializable result."""

    failures: list[str] = []
    if progress:
        await progress("PREPARING", "STARTED")
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
    if request.input_snapshot_hash is not None:
        context = replace(context, input_snapshot_hash=request.input_snapshot_hash)

    instrument_meta = {
        "instrument_id": str(request.instrument_id),
        "market": request.instrument_market,
        "symbol": request.instrument_symbol,
        "currency": request.instrument_currency or request.portfolio.base_currency,
    }
    portfolio_meta = {
        "portfolio_id": str(request.portfolio_id),
        "name": request.portfolio.name,
        "base_currency": request.portfolio.base_currency,
        "cash_balance": str(request.portfolio.cash_balance),
        "status": request.portfolio.status,
    }
    positions_meta = [
        {
            "market": p.market,
            "symbol": p.symbol,
            "name": p.name,
            "currency": p.currency,
            "sector": p.sector,
            "core_quantity": str(p.core_quantity),
            "tactical_quantity": str(p.tactical_quantity),
            "average_cost": str(p.average_cost),
        }
        for p in request.portfolio.positions
    ]
    request_factory = build_analysis_request_factory(
        evidence=request.evidence,
        instrument_meta=instrument_meta,
        portfolio_meta=portfolio_meta,
        positions_meta=positions_meta,
        budget_task_id=request.budget_task_id,
        model_plan=request.model_plan,
        governance=request.governance,
        thesis=request.thesis,
    )
    if progress:
        await progress("PREPARING", "COMPLETED")

    try:
        session = await committee.run_session(
            context=context,
            request_factory=request_factory,
            **({"progress": progress} if progress is not None else {}),
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
        if progress:
            await progress("PORTFOLIO", "STARTED")
        portfolio_result = await _run_single_role(
            committee._agent_runtime,
            role=AgentRole.PORTFOLIO,
            context=context,
            request_factory=request_factory,
        )
        if progress:
            await progress("PORTFOLIO", "COMPLETED")
            await progress("RISK", "STARTED")
        risk_result = await _run_single_role(
            committee._agent_runtime,
            role=AgentRole.RISK,
            context=context,
            request_factory=request_factory,
        )
        if progress:
            await progress("RISK", "COMPLETED")
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

    risk_agent_ok = (
        risk is not None
        and risk.failure is None
        and risk.opinion.stance is not OpinionStance.INSUFFICIENT_DATA
    )
    # If Risk agent output is unusable, keep empty flags (UNKNOWN gate); never invent PASS.
    if not risk_agent_ok and risk is not None:
        failures.append("RISK_AGENT_UNAVAILABLE")

    if risk_agent_ok:
        assessment = build_risk_assessment(
            as_of=request.as_of,
            opinion_results=opinions,
            visible_ids=context.visible_evidence_ids,
        )
    else:
        assessment = build_risk_assessment(
            as_of=request.as_of,
            opinion_results=(),
            visible_ids=frozenset(),
        )
    risk_gate = assessment.gate

    thesis_state = request.thesis_state
    target_position = next(
        (p for p in request.portfolio.positions if p.instrument_id == request.instrument_id), None
    )
    broken_held = (
        thesis_state is ThesisState.BROKEN
        and target_position is not None
        and (target_position.core_quantity + target_position.tactical_quantity > 0)
    )
    if broken_held:
        proposed = Action.REDUCE
        failures.append("THESIS_BROKEN_REVIEW_REQUIRED")
    elif thesis_state is ThesisState.UNKNOWN:
        failures.append("THESIS_UNKNOWN")
    data_sufficient = len(context.visible_evidence_ids) > 0

    # Valuation for all positions (NAV) + target instrument quote.
    if progress:
        await progress("VALUATION_SIZING", "STARTED")
    valuation, sizing, valuation_failures = await _build_valuation_and_sizing(
        request=request,
        market_data=market_data,
        proposed=proposed,
        risk_intent=_risk_intent_from_portfolio(pm.opinion if pm else None),
        assessment=assessment,
        thesis_state=thesis_state,
    )
    failures.extend(valuation_failures)
    if progress:
        await progress("VALUATION_SIZING", "COMPLETED")
    if valuation.get("missing_quotes") and proposed in (Action.BUY, Action.ADD):
        data_sufficient = False

    # Missing valuation/pricing means insufficient data for risk-increasing actions.
    valuation_ok = valuation.get("status") == "OK"
    if proposed in (Action.BUY, Action.ADD) and (
        not valuation_ok or (sizing is None or sizing.get("status") == "FAILED")
    ):
        failures.append("INSUFFICIENT_VALUATION_FOR_EXPOSURE")
        data_sufficient = False
        if proposed is Action.BUY:
            proposed = Action.WATCH

    # TEST_DEFAULT policy is not a real approved policy for new exposure.
    policy_passed = request.governance is not None and request.governance.allows_new_exposure
    if request.governance is not None and not policy_passed:
        failures.append("SIZING_STRATEGY_NOT_APPROVED")

    cio_input = CioAggregationInput(
        proposed_action=proposed,
        investment_quality=_gate_from_stance(
            fundamental.opinion if fundamental else None, positive
        ),
        thesis_state=thesis_state,
        timing=_gate_from_stance(market.opinion if market else None, positive),
        portfolio_fit=_gate_from_stance(pm.opinion if pm else None, positive),
        risk_gate=risk_gate,
        policy_passed=policy_passed,
        data_sufficient=data_sufficient,
    )
    if progress:
        await progress("CIO", "STARTED")
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
        "thesis_version_id": str(request.thesis_version_id) if request.thesis_version_id else None,
        "thesis_state": thesis_state.value,
        "thesis_content_hash": request.thesis.version.content_hash
        if request.thesis and request.thesis.version
        else None,
        "policy_version_id": str(request.governance.policy.policy_version_id)
        if request.governance and request.governance.policy.policy_version_id
        else None,
        "policy_content_hash": request.governance.policy.content_hash
        if request.governance
        else None,
        "governance_hash": request.governance.content_hash if request.governance else None,
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

    if broken_held and target_position is not None:
        decision["core_action"] = "REDUCE" if target_position.core_quantity > 0 else "NONE"
        decision["tactical_action"] = "REDUCE" if target_position.tactical_quantity > 0 else "NONE"

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
    if progress:
        await progress("CIO", "COMPLETED")
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
    instruments: dict[UUID, tuple[str, str, str]] = {
        p.instrument_id: (p.market, p.symbol, p.currency) for p in positions
    }
    if request.instrument_id not in instruments:
        instruments[request.instrument_id] = (
            request.instrument_market,
            request.instrument_symbol,
            request.instrument_currency or request.portfolio.base_currency,
        )
    # Prefer symbol-aware chain API when available.
    quotes = await market_data.get_reference_quotes(
        instrument_ids, as_of=request.as_of, instruments=instruments
    )
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
        "source_rank": target_quote.source_rank,
        "degraded": target_quote.degraded,
        "as_of": target_quote.as_of.isoformat(),
        "target_reference_price": str(target_quote.reference_price),
        "missing_quotes": [],
        "currencies": sorted(currencies),
        "single_currency_limit": True,
        "quote_sources": sorted({q.source for q in quotes.values()}),
        "degraded_instruments": sorted(str(i) for i, q in quotes.items() if q.degraded),
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
                "source": (quotes[p.instrument_id].source if p.instrument_id in quotes else None),
                "degraded": (
                    quotes[p.instrument_id].degraded if p.instrument_id in quotes else None
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
            policy=request.governance.policy.config.to_domain().position
            if request.governance
            else DEFAULT_POSITION_POLICY,
            risk_assessment=assessment,
            thesis_state=thesis_state,
            as_of=UtcTimestamp(request.as_of),
        )
        formula = (
            request.governance.formula.to_domain() if request.governance else DEFAULT_SIZING_FORMULA
        )
        result = size_position(formula, request_obj)
        sizing: dict[str, Any] | None = {
            "formula_version": result.formula_version,
            "input_hash": result.input_hash,
            "target_weight": str(result.target_weight.value),
            "delta_weight": str(result.delta_weight),
            "target_quantity": str(result.target_quantity.value),
            "delta_quantity": str(result.delta_quantity),
            "reason_codes": list(result.reason_codes),
            "policy_version_label": request.policy_version_label,
            "policy_version_id": str(request.governance.policy.policy_version_id)
            if request.governance and request.governance.policy.policy_version_id
            else None,
            "policy_content_hash": request.governance.policy.content_hash
            if request.governance
            else None,
            "formula_status": "TEST_DEFAULT",
        }
    except Exception as exc:  # sizing fail-closed without killing the run
        failures.append("SIZING_INPUT_INVALID")
        sizing = {"status": "FAILED", "reason": str(exc)[:300]}

    return ok_valuation, sizing, failures


def new_run_id() -> UUID:
    return uuid4()
