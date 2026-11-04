"""Deterministic, evidence-backed portfolio risk; no provider, model, or execution authority."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from investment_os.domain.enums import ThesisState
from investment_os.domain.policy import PositionPolicy
from investment_os.domain.risk import RiskAssessment, RiskFlag, RiskFlagKind, RiskSeverity
from investment_os.domain.values import UtcTimestamp, Weight, exact_decimal


@dataclass(frozen=True, slots=True)
class RiskNumbers:
    instrument_weight: Weight
    sector_weight: Weight
    gross_exposure: Weight
    cash_weight: Weight
    pending_instrument: Weight
    pending_sector: Weight
    pending_gross: Weight
    volatility: Decimal
    liquidity_capacity: Weight
    risk_budget_capacity: Weight
    correlation: Decimal
    max_correlation: Decimal
    max_volatility: Decimal
    core_weight: Weight
    tactical_weight: Weight
    thesis_state: ThesisState
    policy: PositionPolicy
    evidence_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        for field in ("volatility", "correlation", "max_correlation", "max_volatility"):
            object.__setattr__(self, field, exact_decimal(getattr(self, field)))
        if not self.evidence_ids or self.volatility <= 0 or self.max_volatility <= 0:
            raise ValueError("complete positive risk inputs and evidence required")
        if not -1 <= self.correlation <= 1 or not -1 <= self.max_correlation <= 1:
            raise ValueError("correlation must be a fraction between -1 and 1")
        if self.core_weight.value + self.tactical_weight.value != self.instrument_weight.value:
            raise ValueError("Core/Tactical risk must reconcile with instrument exposure")


def evaluate_numeric_risk(
    numbers: RiskNumbers, *, identifier: UUID, as_of: UtcTimestamp, expires_at: UtcTimestamp
) -> RiskAssessment:
    flags: list[RiskFlag] = []

    def flag(code: str, hard: bool, release: str) -> None:
        flags.append(
            RiskFlag(
                code,
                RiskFlagKind.HARD if hard else RiskFlagKind.SOFT,
                RiskSeverity.HIGH if hard else RiskSeverity.LOW,
                tuple(dict.fromkeys(numbers.evidence_ids)),
                release,
            )
        )

    checks = (
        (
            numbers.instrument_weight.value + numbers.pending_instrument.value,
            numbers.policy.single_instrument_max.value,
            "SINGLE_INSTRUMENT_LIMIT",
        ),
        (
            numbers.sector_weight.value + numbers.pending_sector.value,
            numbers.policy.sector_max.value,
            "SECTOR_CONCENTRATION_LIMIT",
        ),
        (
            numbers.gross_exposure.value + numbers.pending_gross.value,
            numbers.policy.gross_exposure_max.value,
            "GROSS_EXPOSURE_LIMIT",
        ),
    )
    for actual, limit, code in checks:
        if actual > limit:
            flag(code, True, "重新评估组合及预占暴露, 确认已回到固定Policy上限内")
    if numbers.cash_weight.value - numbers.pending_gross.value < numbers.policy.minimum_cash.value:
        flag("MINIMUM_CASH_LIMIT", True, "恢复固定Policy要求的可用现金后重新评估")
    if numbers.liquidity_capacity.value == 0:
        flag("LIQUIDITY_INSUFFICIENT", True, "取得有效可追溯流动性容量后重新评估")
    if numbers.thesis_state is ThesisState.BROKEN:
        flag("THESIS_BROKEN_NO_INCREASE", True, "修复证据并生成有效的新论点; 不能覆盖旧Veto")
    if numbers.correlation > numbers.max_correlation:
        flag("CORRELATION_ELEVATED", False, "检查共同因子及固定Policy相关性关注条件")
    if numbers.volatility > numbers.max_volatility:
        flag("VOLATILITY_ELEVATED", False, "保留波动缩放和人工关注, 不放松任何硬上限")
    if numbers.risk_budget_capacity.value == 0:
        flag("RISK_BUDGET_EXHAUSTED", False, "重新取得受约束风险预算容量; 不默认补值")
    if not flags:
        flag("NUMERIC_LIMITS_EVALUATED", False, "在输入或Policy变化、资料失效前重新评估")
    return RiskAssessment(identifier, 1, as_of, expires_at, tuple(flags))
