"""Consistent read-only P5 input capture; no inferred historical holdings."""

import json
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.policy_schema import InvestmentPolicySchema
from investment_os.application.portfolio_valuation import (
    FrozenHolding,
    FrozenPolicy,
    FrozenPortfolio,
)
from investment_os.infrastructure.persistence.models import (
    InstrumentRecord,
    InvestmentPolicyRecord,
    InvestmentPolicyVersionRecord,
    PortfolioRecord,
    PositionRecord,
)


class SqlValuationInputs:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self._sessions = sessions

    async def capture(self, portfolio_id: UUID) -> FrozenPortfolio:
        async with self._sessions() as session, session.begin():
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            captured_at = await session.scalar(select(text("transaction_timestamp()")))
            portfolio = await session.get(PortfolioRecord, portfolio_id)
            if portfolio is None:
                raise ValueError("VALUATION_PORTFOLIO_NOT_FOUND")
            rows = (
                await session.execute(
                    select(PositionRecord, InstrumentRecord)
                    .outerjoin(
                        InstrumentRecord, PositionRecord.instrument_id == InstrumentRecord.id
                    )
                    .where(PositionRecord.portfolio_id == portfolio_id)
                    .order_by(PositionRecord.instrument_id)
                )
            ).all()
            holdings = []
            for position, instrument in rows:
                if instrument is None:
                    raise ValueError("VALUATION_INSTRUMENT_MISSING")
                holdings.append(
                    FrozenHolding(
                        position_id=position.id,
                        instrument_id=instrument.id,
                        version=position.version,
                        market=instrument.exchange,
                        symbol=instrument.symbol,
                        name=instrument.name,
                        currency=instrument.currency,
                        sector=instrument.sector,
                        lot_size=instrument.lot_size,
                        core_quantity=position.core_quantity,
                        tactical_quantity=position.tactical_quantity,
                        core_average_cost=position.core_average_cost,
                        tactical_average_cost=position.tactical_average_cost,
                    )
                )
            active = (
                await session.scalars(
                    select(InvestmentPolicyRecord)
                    .where(InvestmentPolicyRecord.status == "ACTIVE")
                    .order_by(InvestmentPolicyRecord.id)
                    .limit(2)
                )
            ).all()
            policy = FrozenPolicy(status="MISSING", reason_code="POLICY_MISSING")
            if len(active) > 1:
                policy = FrozenPolicy(status="AMBIGUOUS", reason_code="POLICY_AMBIGUOUS")
            elif active:
                record = active[0]
                version = (
                    await session.get(InvestmentPolicyVersionRecord, record.current_version_id)
                    if record.current_version_id
                    else None
                )
                reason = "POLICY_VERSION_MISSING"
                if version:
                    reason = "POLICY_REFERENCE_VALID"
                    if version.policy_id != record.id:
                        reason = "POLICY_VERSION_MISMATCH"
                    elif portfolio.policy_id is not None and portfolio.policy_id != record.id:
                        reason = "PORTFOLIO_POLICY_MISMATCH"
                    elif record.name.upper().startswith("TEST"):
                        reason = "POLICY_TEST_DEFAULT"
                    elif (
                        not version.approved_by
                        or not version.approved_at
                        or not version.effective_from
                    ):
                        reason = "POLICY_APPROVAL_MISSING"
                    elif (
                        version.approved_at > captured_at
                        or version.effective_from > captured_at
                        or version.effective_from < version.approved_at
                    ):
                        reason = "POLICY_NOT_EFFECTIVE"
                    elif version.metadata_json.get("approved_by_actor") != "HUMAN":
                        reason = "POLICY_HUMAN_APPROVAL_UNVERIFIED"
                    try:
                        document = InvestmentPolicySchema.model_validate_json(
                            json.dumps(version.config_json)
                        )
                        if (
                            record.name.upper().startswith("TEST")
                            or document.metadata.status.value == "TEST_DEFAULT"
                        ):
                            reason = "POLICY_TEST_DEFAULT"
                        elif document.metadata.status.value != "ACTIVE":
                            reason = "POLICY_NOT_ACTIVE"
                    except ValueError:
                        reason = "POLICY_CONFIG_INVALID"
                policy = FrozenPolicy(
                    policy_id=record.id,
                    version_id=version.id if version else None,
                    version=version.version if version else None,
                    name=record.name,
                    content_hash=version.content_hash if version else None,
                    config_json=json.dumps(
                        version.config_json, sort_keys=True, separators=(",", ":")
                    )
                    if version
                    else None,
                    status=record.status,
                    reason_code=reason,
                )
            return FrozenPortfolio(
                portfolio_id=portfolio.id,
                name=portfolio.name,
                base_currency=portfolio.base_currency,
                cash=portfolio.cash_balance,
                captured_at=captured_at,
                holdings=tuple(holdings),
                policy=policy,
            )
