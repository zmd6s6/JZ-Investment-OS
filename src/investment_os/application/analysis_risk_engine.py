"""Deterministic preparation and sizing over a fixed, qualified shadow input graph."""

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Protocol
from uuid import UUID, uuid4

from investment_os.application.analysis_risk_sizing import (
    NumericSourceSnapshot,
    RiskSizingView,
    portfolio_identity,
)
from investment_os.application.analysis_runs import AnalysisFrozenInput, AnalysisStorePort
from investment_os.application.policy_schema import InvestmentPolicySchema
from investment_os.domain.enums import Action, PositionBucket, RiskIntent, ThesisState
from investment_os.domain.portfolio import PortfolioCapacityInputs
from investment_os.domain.risk import RiskAssessment
from investment_os.domain.risk_evaluation import RiskNumbers, evaluate_numeric_risk
from investment_os.domain.sizing import SizingRequest, size_position
from investment_os.domain.valuation import HoldingInput, PortfolioNumbers, value_portfolio
from investment_os.domain.values import Quantity, UtcTimestamp, Weight


@dataclass(frozen=True)
class RiskPrepared:
    view: RiskSizingView
    risk: RiskAssessment | None
    policy: InvestmentPolicySchema | None
    capacity: PortfolioCapacityInputs | None
    valuation: PortfolioNumbers | None
    source: NumericSourceSnapshot | None
    prices: dict[UUID, Decimal]


def prepare_risk(
    frozen: AnalysisFrozenInput,
    *,
    pending: tuple[Decimal, Decimal, Decimal] | None,
    pending_reasons: tuple[str, ...],
    evaluated_at: datetime,
) -> RiskPrepared:
    book = frozen.queued.valuation.input_snapshot
    target_id = frozen.instrument_id
    source = frozen.numeric_source
    reasons = [*pending_reasons, *frozen.blockers]
    schema = None
    try:
        if book.policy.reason_code != "POLICY_REFERENCE_VALID" or book.policy.status != "ACTIVE":
            raise ValueError(book.policy.reason_code)
        schema = InvestmentPolicySchema.model_validate_json(book.policy.config_json or "{}")
        if schema.metadata.status.value != "ACTIVE":
            raise ValueError("POLICY_NOT_ACTIVE")
        if schema.sizing is None:
            raise ValueError("POLICY_SIZING_RULES_MISSING")
    except ValueError as error:
        reasons.append(str(error) if str(error).startswith("POLICY_") else "POLICY_CONFIG_INVALID")
    if source is None:
        reasons.append("NUMERIC_SOURCE_NOT_SELECTED")
    else:
        if (
            source.portfolio_id != book.portfolio_id
            or source.instrument_id != target_id
            or source.policy_version_id != book.policy.version_id
            or source.portfolio_identity_hash != portfolio_identity(book)
        ):
            reasons.append("NUMERIC_FROZEN_IDENTITY_MISMATCH")
        if source.source_kind != "SYNTHETIC_FIXTURE":
            reasons.append("REFERENCE_NUMBERS_NOT_QUALIFIED")
        if source.created_at > frozen.queued.queued_at or source.as_of > book.captured_at:
            reasons.append("NUMERIC_INPUT_NOT_AVAILABLE_AT_CAPTURE")
        if evaluated_at >= source.expires_at:
            reasons.append("NUMERIC_INPUT_EXPIRED")
    if book.base_currency != "CNY" or any(h.currency != "CNY" for h in book.holdings):
        reasons.append("FX_REQUIRED")
    if source is not None and source.target.currency != "CNY":
        reasons.append("FX_REQUIRED")
    evidence = {item.evidence_id: item for item in frozen.evidence}
    facts = {(fact.metric, fact.instrument_id): fact for fact in source.facts} if source else {}
    expires = [source.expires_at] if source else []
    for fact in facts.values():
        assert source is not None
        item = evidence.get(fact.evidence_id)
        if item is None:
            reasons.append(f"NUMERIC_EVIDENCE_MISSING:{fact.metric}")
        elif (
            item.instrument_id not in {None, fact.instrument_id}
            or item.freshness != "FRESH"
            or item.expires_at is None
            or evaluated_at >= item.expires_at
            or max(item.observed_at, item.effective_at, item.available_at, item.ingested_at)
            > source.as_of
        ):
            reasons.append(f"NUMERIC_EVIDENCE_INELIGIBLE:{fact.metric}")
        else:
            expires.append(item.expires_at)
    prices: dict[UUID, Decimal] = {}
    needed = {
        h.instrument_id for h in book.holdings if h.core_quantity + h.tactical_quantity > 0
    } | {target_id}
    for identifier in needed:
        price_fact = facts.get(("REFERENCE_PRICE", identifier))
        if price_fact is None or price_fact.value <= 0 or price_fact.currency != "CNY":
            reasons.append(f"REFERENCE_PRICE_MISSING_OR_INVALID:{identifier}")
        else:
            prices[identifier] = price_fact.value
    metric_values: dict[str, Decimal] = {}
    for metric in ("VOLATILITY", "LIQUIDITY_CAPACITY", "RISK_BUDGET_CAPACITY", "CORRELATION"):
        metric_fact = facts.get((metric, target_id))
        if metric_fact is None:
            reasons.append(f"{metric}_MISSING")
        elif (
            (metric == "VOLATILITY" and metric_fact.value <= 0)
            or (
                metric in {"LIQUIDITY_CAPACITY", "RISK_BUDGET_CAPACITY"}
                and not 0 <= metric_fact.value <= 1
            )
            or (metric == "CORRELATION" and not -1 <= metric_fact.value <= 1)
        ):
            reasons.append(f"{metric}_INVALID")
        else:
            metric_values[metric] = metric_fact.value
    if frozen.thesis_state == "UNKNOWN" or not frozen.thesis_version_id:
        reasons.append("THESIS_MISSING_OR_UNAVAILABLE")
    if pending is None:
        reasons.append("PENDING_CAPACITY_UNAVAILABLE")
    if frozen.queued.command.position_bucket is None:
        reasons.append("POSITION_BUCKET_NOT_SELECTED")
    valuation = value_portfolio(
        book.base_currency,
        book.cash,
        tuple(
            HoldingInput(
                h.instrument_id,
                h.currency,
                h.sector,
                h.core_quantity,
                h.tactical_quantity,
                prices.get(h.instrument_id),
            )
            for h in book.holdings
        ),
    )
    if valuation.nav is None or valuation.nav <= 0:
        reasons.append("NAV_UNAVAILABLE")
    numbers: dict[str, object] = {
        "fx_status": "NOT_REQUIRED_CNY" if "FX_REQUIRED" not in reasons else "MISSING",
        "cash": str(book.cash),
        "nav": str(valuation.nav) if valuation.nav is not None else None,
        "source_kind": source.source_kind if source else None,
        "source_name": source.source_name if source else None,
        "reference_price": str(prices[target_id]) if target_id in prices else None,
        "metrics": {key: str(value) for key, value in metric_values.items()},
        "pending": [str(value) for value in pending] if pending is not None else None,
        "portfolio_identity_hash": portfolio_identity(book),
        "input_hash": frozen.input_hash,
    }
    base = RiskSizingView(
        numeric_snapshot_id=source.snapshot_id if source else None,
        policy_version_id=book.policy.version_id,
        bucket=frozen.queued.command.position_bucket,
        blockers=tuple(sorted(set(reasons))),
        numbers=numbers,
        evaluated_at=evaluated_at,
        expires_at=min(expires) if expires else None,
    )
    if reasons:
        return RiskPrepared(base, None, schema, None, valuation, source, prices)
    assert source is not None and schema is not None and schema.sizing is not None
    assert pending is not None and valuation.nav is not None
    assert valuation.cash_weight is not None and valuation.gross_exposure is not None
    holding = next((h for h in valuation.holdings if h.instrument_id == target_id), None)
    core = holding.core_weight if holding else Decimal(0)
    tactical = holding.tactical_weight if holding else Decimal(0)
    assert core is not None and tactical is not None
    sector = dict(valuation.sector_weights).get(source.target.sector, Decimal(0))
    with localcontext() as decimal_context:
        decimal_context.prec = 80
        instrument = core + tactical
        risk_numbers = RiskNumbers(
            Weight(instrument),
            Weight(sector),
            Weight(valuation.gross_exposure),
            Weight(valuation.cash_weight),
            Weight(pending[0]),
            Weight(pending[1]),
            Weight(pending[2]),
            metric_values["VOLATILITY"],
            Weight(metric_values["LIQUIDITY_CAPACITY"]),
            Weight(metric_values["RISK_BUDGET_CAPACITY"]),
            metric_values["CORRELATION"],
            schema.sizing.correlation_attention_threshold,
            schema.sizing.max_instrument_volatility,
            Weight(core),
            Weight(tactical),
            ThesisState(frozen.thesis_state),
            schema.to_domain().position,
            tuple(sorted({fact.evidence_id for fact in facts.values()}, key=str)),
        )
        risk = evaluate_numeric_risk(
            risk_numbers,
            identifier=uuid4(),
            as_of=UtcTimestamp(frozen.as_of),
            expires_at=UtcTimestamp(min(expires)),
        )
        capacity = PortfolioCapacityInputs(
            Weight(instrument),
            Weight(sector),
            Weight(valuation.gross_exposure),
            Weight(pending[0]),
            Weight(pending[1]),
            Weight(pending[2]),
            Weight(metric_values["RISK_BUDGET_CAPACITY"]),
            Weight(metric_values["LIQUIDITY_CAPACITY"]),
        )
    numbers.update(
        {
            "core_weight": str(core),
            "tactical_weight": str(tactical),
            "instrument_weight": str(instrument),
            "sector_weight": str(sector),
            "gross_exposure": str(valuation.gross_exposure),
            "cash_weight": str(valuation.cash_weight),
        }
    )
    view = base.model_copy(
        update={
            "risk_gate": risk.gate.value,
            "risk_assessment_id": risk.id,
            "risk_flags": tuple(
                json.loads(json.dumps(asdict(flag), default=str)) for flag in risk.flags
            ),
            "numbers": numbers,
        }
    )
    return RiskPrepared(view, risk, schema, capacity, valuation, source, prices)


def compute_sizing(
    prepared: RiskPrepared, frozen: AnalysisFrozenInput, *, action: Action, intent: RiskIntent
) -> tuple[RiskSizingView, SizingRequest | None]:
    view = prepared.view
    if view.blockers or prepared.risk is None:
        return view, None
    assert prepared.policy is not None and prepared.policy.sizing is not None
    assert (
        prepared.source is not None
        and prepared.valuation is not None
        and prepared.capacity is not None
    )
    bucket = frozen.queued.command.position_bucket
    assert bucket is not None and prepared.valuation.nav is not None
    if action not in {Action.BUY, Action.ADD, Action.REDUCE, Action.EXIT}:
        return view.model_copy(
            update={"blockers": ("CANDIDATE_ACTION_HAS_NO_POSITION_CHANGE",)}
        ), None
    if prepared.risk.gate.value == "VETO" and action in {Action.BUY, Action.ADD}:
        return view.model_copy(update={"blockers": ("RISK_VETO_NO_EXPOSURE_INCREASE",)}), None
    book = frozen.queued.valuation.input_snapshot
    holding = next((h for h in book.holdings if h.instrument_id == frozen.instrument_id), None)
    quantity = (
        (holding.core_quantity if bucket is PositionBucket.CORE else holding.tactical_quantity)
        if holding
        else Decimal(0)
    )
    price = prepared.prices[frozen.instrument_id]
    with localcontext() as decimal_context:
        decimal_context.prec = 80
        weight = quantity * price / prepared.valuation.nav
        request = SizingRequest(
            action,
            bucket,
            intent,
            Weight(weight),
            Quantity(quantity),
            prepared.valuation.nav,
            price,
            Quantity(prepared.source.target.lot_size),
            Decimal(str(view.numbers["metrics"]["VOLATILITY"])),  # type: ignore[index]
            prepared.capacity,
            prepared.policy.to_domain().position,
            prepared.risk,
            ThesisState(frozen.thesis_state),
            UtcTimestamp(frozen.as_of),
        )
        result = size_position(prepared.policy.sizing.to_formula(), request)
    return view.model_copy(
        update={
            "sizing_status": "COMPUTED",
            "target_quantity": result.target_quantity.value,
            "delta_quantity": result.delta_quantity,
            "sizing_input": json.loads(json.dumps(asdict(request), default=str)),
            "sizing_output": json.loads(json.dumps(asdict(result), default=str)),
        }
    ), request


class RiskSizingPort(Protocol):
    async def risk(
        self, run_id: UUID, lease: UUID, frozen: AnalysisFrozenInput, committee_id: UUID
    ) -> RiskPrepared: ...
    async def sizing(
        self,
        run_id: UUID,
        lease: UUID,
        frozen: AnalysisFrozenInput,
        prepared: RiskPrepared,
        *,
        action: Action,
        intent: RiskIntent,
    ) -> RiskSizingView: ...


class UnavailableRiskSizing:
    """Explicitly unavailable composition; never fabricate a numeric input or PASS."""

    def __init__(self, store: AnalysisStorePort):
        self._store = store

    async def risk(
        self, run_id: UUID, lease: UUID, frozen: AnalysisFrozenInput, committee_id: UUID
    ) -> RiskPrepared:
        prepared = prepare_risk(
            frozen,
            pending=None,
            pending_reasons=("DETERMINISTIC_RISK_INPUTS_UNAVAILABLE",),
            evaluated_at=datetime.now(UTC),
        )
        await self._store.step(
            run_id,
            lease,
            stage="RISK",
            status="BLOCKED",
            payload=prepared.view.model_dump(mode="json"),
            reason_code="DETERMINISTIC_RISK_INPUTS_UNAVAILABLE",
        )
        return prepared

    async def sizing(
        self,
        run_id: UUID,
        lease: UUID,
        frozen: AnalysisFrozenInput,
        prepared: RiskPrepared,
        *,
        action: Action,
        intent: RiskIntent,
    ) -> RiskSizingView:
        await self._store.step(
            run_id,
            lease,
            stage="SIZING",
            status="BLOCKED",
            payload=prepared.view.model_dump(mode="json"),
            reason_code="SIZING_INPUTS_INCOMPLETE",
        )
        return prepared.view
