"""Read a specific approved policy, or the published and explicitly test-only fallback."""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.analysis_governance import FrozenAnalysisPolicy, policy_config_hash
from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.policy_schema import InvestmentPolicySchema
from investment_os.infrastructure.persistence.models import (
    InvestmentPolicyRecord,
    InvestmentPolicyVersionRecord,
    PortfolioRecord,
)


class SqlAnalysisPolicies:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @staticmethod
    def _test_config() -> InvestmentPolicySchema:
        return InvestmentPolicySchema.model_validate_json(
            (
                Path(__file__).resolve().parents[3] / "config/investment-policy.test-default.json"
            ).read_text(encoding="utf-8")
        )

    async def policy(self, portfolio_id: UUID | None, *, as_of: datetime) -> FrozenAnalysisPolicy:
        try:
            async with self._sessions() as session:
                bound_id = None
                if portfolio_id is not None:
                    portfolio = await session.get(PortfolioRecord, portfolio_id)
                    if portfolio is None:
                        raise ApplicationError(
                            ApplicationErrorCode.PORTFOLIO_NOT_FOUND, "portfolio not found"
                        )
                    bound_id = portfolio.policy_id
                if bound_id is not None:
                    policy = await session.get(InvestmentPolicyRecord, bound_id)
                    if policy is None or policy.status != "ACTIVE":
                        raise ValueError("bound policy is not active")
                else:
                    policies = list(
                        await session.scalars(
                            select(InvestmentPolicyRecord)
                            .where(InvestmentPolicyRecord.status == "ACTIVE")
                            .limit(2)
                        )
                    )
                    if len(policies) > 1:
                        raise ValueError("active policy is ambiguous")
                    policy = policies[0] if policies else None
                if policy is None:
                    config = await asyncio.to_thread(self._test_config)
                    frozen = FrozenAnalysisPolicy(
                        mode="TEST_DEFAULT",
                        version=1,
                        config=config,
                        content_hash=policy_config_hash(config),
                    )
                else:
                    version = (
                        await session.get(InvestmentPolicyVersionRecord, policy.current_version_id)
                        if policy.current_version_id
                        else None
                    )
                    if version is None or version.policy_id != policy.id:
                        raise ValueError(
                            "active policy version is missing or belongs to another policy"
                        )
                    config = InvestmentPolicySchema.model_validate_json(
                        json.dumps(version.config_json)
                    )
                    if config.metadata.name != policy.name:
                        raise ValueError("policy name differs from approved document")
                    frozen = FrozenAnalysisPolicy(
                        mode="ACTIVE",
                        policy_id=policy.id,
                        policy_version_id=version.id,
                        version=version.version,
                        config=config,
                        content_hash=version.content_hash,
                        effective_from=version.effective_from,
                        approved_by=version.approved_by,
                        approved_at=version.approved_at,
                        approved_by_actor=version.metadata_json.get("approved_by_actor"),
                    )
                frozen.require_available(as_of)
                return frozen
        except (ValueError, OSError, TypeError):
            raise ApplicationError(
                ApplicationErrorCode.ANALYSIS_POLICY_INVALID,
                "policy is invalid, ambiguous, unapproved or not effective; no fallback selected",
            ) from None
