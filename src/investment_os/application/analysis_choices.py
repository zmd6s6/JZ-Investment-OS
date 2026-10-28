"""Secret-free, explicitly selectable analysis inputs. Reading never invokes a provider."""

from typing import Protocol
from uuid import UUID

from pydantic import AwareDatetime

from investment_os.application.analysis_runs import ANALYSIS_ROLES, AnalysisDto
from investment_os.application.llm_budget import LLMBudgetService
from investment_os.application.provider_settings import ProviderSettingsService


class AnalysisEvidenceChoice(AnalysisDto):
    evidence_id: UUID
    source_name: str
    source_locator: str
    observed_at: AwareDatetime
    expires_at: AwareDatetime | None
    freshness: str
    excerpt: str


class AnalysisProfileChoice(AnalysisDto):
    profile_id: UUID
    name: str
    kind: str
    model_name: str | None = None
    pricing_configured: bool = False


class AnalysisChoices(AnalysisDto):
    roles: tuple[str, ...]
    models: tuple[AnalysisProfileChoice, ...]
    data_profiles: tuple[AnalysisProfileChoice, ...]
    evidence: tuple[AnalysisEvidenceChoice, ...]
    budget_configured: bool
    budget_version: str | None
    budget_currency: str | None = None
    task_token_limit: int | None = None
    task_cost_limit: str | None = None
    remaining_tokens: int | None
    remaining_cost: str | None
    max_model_calls: int = 42


class AnalysisEvidenceChoicesPort(Protocol):
    async def list_evidence(self, instrument_id: UUID) -> tuple[AnalysisEvidenceChoice, ...]: ...


class AnalysisChoicesService:
    def __init__(
        self,
        evidence: AnalysisEvidenceChoicesPort,
        providers: ProviderSettingsService,
        budget: LLMBudgetService,
    ):
        self._evidence, self._providers, self._budget = evidence, providers, budget

    async def get(self, instrument_id: UUID) -> AnalysisChoices:
        models = await self._providers.list_model_profiles()
        data = await self._providers.list_data_profiles()
        policy, usage = await self._budget.policy(), await self._budget.usage()
        return AnalysisChoices(
            roles=tuple(role.value for role in ANALYSIS_ROLES),
            models=tuple(
                AnalysisProfileChoice(
                    profile_id=p.id,
                    name=p.name,
                    kind=p.provider_type,
                    model_name=p.model_name,
                    pricing_configured=all(
                        v is not None
                        for v in (
                            p.pricing_version,
                            p.pricing_currency,
                            p.input_token_price,
                            p.output_token_price,
                            p.pricing_effective_at,
                        )
                    ),
                )
                for p in models
                if p.enabled
                and p.credential_ref is not None
                and p.provider_type == "OPENAI_COMPATIBLE"
            ),
            data_profiles=tuple(
                AnalysisProfileChoice(profile_id=p.id, name=p.name, kind=p.provider_type)
                for p in data
                if p.enabled
                and p.credential_ref is not None
                and p.provider_type == "BOCHA_WEB_SEARCH"
            ),
            evidence=await self._evidence.list_evidence(instrument_id),
            budget_configured=policy is not None,
            budget_version=policy.version if policy else None,
            budget_currency=policy.currency if policy else None,
            task_token_limit=policy.task_token_limit if policy else None,
            task_cost_limit=str(policy.task_cost_limit) if policy else None,
            remaining_tokens=usage.remaining_tokens if usage else None,
            remaining_cost=str(usage.remaining_cost) if usage else None,
        )
