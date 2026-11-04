"""Frozen provider/budget routing and current Evidence/Thesis preparation for one run."""

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.analysis_configuration import budget_hash, profile_hash
from investment_os.application.analysis_runs import (
    AnalysisCancelled,
    AnalysisEvidenceInput,
    AnalysisFrozenInput,
    AnalysisQueuedInput,
    AnalysisStorePort,
)
from investment_os.application.evidence import derive_display_freshness
from investment_os.application.llm_budget import LLMBudgetPolicyChanged, LLMBudgetService
from investment_os.application.llm_gateway import (
    LLMGatewayFailure,
    LLMGatewayPort,
    LLMGatewayRequest,
    LLMGatewayResponse,
)
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.application.provider_settings import (
    ModelProviderProfile,
    ProviderSettingsService,
)
from investment_os.application.research import ResearchRequest
from investment_os.application.research_runtime import (
    ResearchProviderProfileChangedError,
    ResearchProviderRuntime,
)
from investment_os.application.secrets import SecretStore
from investment_os.domain.agent import AgentRole
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.analysis_risk_sizing import SqlNumericSources
from investment_os.infrastructure.evidence_ingestion import SqlAlchemyEvidenceIngestor
from investment_os.infrastructure.openai_compatible_llm import (
    ModelProfileChanged,
    OpenAICompatibleLLMGateway,
)
from investment_os.infrastructure.persistence.models import EvidenceRecord
from investment_os.infrastructure.thesis_engine import SqlAlchemyThesisReader


class PinnedModelResolver:
    def __init__(self, providers: ProviderSettingsService, queued: AnalysisQueuedInput):
        self._providers = providers
        self._queued = queued

    async def model_for_role(self, role: str) -> ModelProviderProfile:
        selected = self._queued.models[AgentRole(role)]
        actual = await self._providers.get_model_profile(selected.profile_id)
        if actual is None or not actual.enabled or profile_hash(actual) != selected.config_hash:
            raise ValueError("ANALYSIS_MODEL_PROFILE_CHANGED")
        return actual


class PinnedAnalysisGateway:
    def __init__(
        self,
        resolver: PinnedModelResolver,
        budget: LLMBudgetService,
        queued: AnalysisQueuedInput,
        delegate: LLMGatewayPort,
        store: AnalysisStorePort,
        run_id: UUID,
        lease: UUID,
    ):
        self._resolver = resolver
        self._budget = budget
        self._queued = queued
        self._delegate = delegate
        self._store = store
        self._run_id = run_id
        self._lease = lease

    async def complete(self, request: LLMGatewayRequest) -> LLMGatewayResponse:
        try:
            await self._store.check_running(self._run_id, self._lease)
            await self._resolver.model_for_role(request.role.value)
            current = await self._budget.policy()
            if current is None or budget_hash(current) != self._queued.budget_hash:
                raise ValueError("ANALYSIS_BUDGET_CHANGED")
            await self._store.check_running(self._run_id, self._lease)
        except (AnalysisCancelled, ValueError) as exc:
            code = "ANALYSIS_CANCEL_REQUESTED" if isinstance(exc, AnalysisCancelled) else str(exc)
            await self._store.step(
                self._run_id,
                self._lease,
                stage="MODEL_CALL",
                status="BLOCKED",
                payload={"role": request.role.value, "repair_attempt": request.repair_attempt},
                reason_code=code,
            )
            raise LLMGatewayFailure(
                "analysis input or cancellation gate blocked the call"
            ) from None
        await self._store.step(
            self._run_id,
            self._lease,
            stage="MODEL_CALL",
            status="RUNNING",
            payload={
                "role": request.role.value,
                "repair_attempt": request.repair_attempt,
                "max_output_tokens": request.max_output_tokens,
            },
        )
        try:
            response = await self._delegate.complete(
                replace(
                    request,
                    expected_budget_policy_hash=self._queued.budget_hash,
                    expected_model_profile_hash=self._queued.models[request.role].config_hash,
                )
            )
        except (LLMBudgetPolicyChanged, ModelProfileChanged) as exc:
            await self._store.step(
                self._run_id,
                self._lease,
                stage="MODEL_CALL",
                status="BLOCKED",
                payload={"role": request.role.value, "egress": False, "cost_unconfirmed": False},
                reason_code=(
                    "ANALYSIS_MODEL_PROFILE_CHANGED"
                    if isinstance(exc, ModelProfileChanged)
                    else "ANALYSIS_BUDGET_CHANGED"
                ),
            )
            raise
        except Exception:
            await self._store.step(
                self._run_id,
                self._lease,
                stage="MODEL_CALL",
                status="FAILED",
                payload={
                    "role": request.role.value,
                    "repair_attempt": request.repair_attempt,
                    "cost_unconfirmed": True,
                },
                reason_code="MODEL_CALL_FAILED",
            )
            raise
        await self._store.step(
            self._run_id,
            self._lease,
            stage="MODEL_CALL",
            status="COMPLETED",
            payload={
                "role": request.role.value,
                "repair_attempt": request.repair_attempt,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cost": str(response.total_cost) if response.total_cost is not None else None,
            },
        )
        return response


class AnalysisGatewayFactory:
    def __init__(
        self,
        providers: ProviderSettingsService,
        secrets: SecretStore,
        budget: LLMBudgetService,
        store: AnalysisStorePort,
        *,
        client: httpx.AsyncClient | None = None,
    ):
        self._providers = providers
        self._secrets = secrets
        self._budget = budget
        self._client = client or httpx.AsyncClient(follow_redirects=False)
        self._owns_client = client is None
        self._store = store

    def gateway_for(self, run_id: UUID, lease: UUID, queued: AnalysisQueuedInput) -> LLMGatewayPort:
        resolver = PinnedModelResolver(self._providers, queued)
        delegate = OpenAICompatibleLLMGateway(
            provider_settings=resolver,
            secret_store=self._secrets,
            budget_service=self._budget,
            client=self._client,
        )
        return PinnedAnalysisGateway(
            resolver, self._budget, queued, delegate, self._store, run_id, lease
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class SqlAnalysisInputPreparer:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        store: AnalysisStorePort,
        providers: ProviderSettingsService,
        research: ResearchProviderRuntime,
        ingestor: SqlAlchemyEvidenceIngestor,
    ):
        self._sessions = sessions
        self._store = store
        self._providers = providers
        self._research = research
        self._ingestor = ingestor

    async def prepare(
        self, run_id: UUID, lease: UUID, queued: AnalysisQueuedInput
    ) -> AnalysisFrozenInput:
        identifiers = list(queued.command.evidence_ids)
        numeric_source = None
        numeric_blockers = []
        if queued.command.numeric_snapshot_id is not None:
            try:
                numeric_source = await SqlNumericSources(self._sessions).get(
                    queued.command.numeric_snapshot_id
                )
                identifiers.extend(fact.evidence_id for fact in numeric_source.facts)
            except ValueError as error:
                numeric_blockers.append(str(error))
        for selected in queued.data_profiles:
            await self._store.check_running(run_id, lease)
            profile = await self._providers.get_data_profile(selected.profile_id)
            if (
                profile is None
                or not profile.enabled
                or profile_hash(profile) != selected.config_hash
            ):
                raise ValueError("ANALYSIS_DATA_PROFILE_CHANGED")
            await self._store.step(
                run_id,
                lease,
                stage="RESEARCH",
                status="RUNNING",
                payload={
                    "profile_id": str(selected.profile_id),
                    "name": selected.name,
                    "query": queued.command.query,
                    "max_results": queued.command.max_results,
                },
            )
            started = monotonic()
            try:
                artifacts = await self._research.fetch(
                    profile_id=selected.profile_id,
                    expected_profile_hash=selected.config_hash,
                    request=ResearchRequest(
                        instrument_ids=(queued.command.instrument_id,),
                        as_of=UtcTimestamp(datetime.now(UTC)),
                        query=queued.command.query,
                        max_results=queued.command.max_results,
                    ),
                )
                if len(artifacts) > queued.command.max_results:
                    raise ValueError("ANALYSIS_DATA_RESPONSE_LIMIT")
                for artifact in artifacts:
                    if artifact.instrument_id not in {None, queued.command.instrument_id}:
                        raise ValueError("ANALYSIS_DATA_TARGET_MISMATCH")
                    saved = await self._ingestor.ingest(artifact, correlation_id=run_id)
                    identifiers.append(saved.evidence_id)
            except ResearchProviderProfileChangedError:
                await self._store.step(
                    run_id,
                    lease,
                    stage="RESEARCH",
                    status="BLOCKED",
                    payload={"profile_id": str(selected.profile_id), "egress": False},
                    reason_code="ANALYSIS_DATA_PROFILE_CHANGED",
                )
                raise ValueError("ANALYSIS_DATA_PROFILE_CHANGED") from None
            except Exception:
                await self._store.step(
                    run_id,
                    lease,
                    stage="RESEARCH",
                    status="FAILED",
                    payload={"profile_id": str(selected.profile_id)},
                    reason_code="ANALYSIS_RESEARCH_FAILED",
                )
                raise ValueError("ANALYSIS_RESEARCH_FAILED") from None
            await self._providers.record_data_provider_sync(
                profile_id=selected.profile_id,
                artifact_count=len(artifacts),
                latency_ms=int((monotonic() - started) * 1000),
            )
            await self._store.step(
                run_id,
                lease,
                stage="RESEARCH",
                status="COMPLETED",
                payload={"profile_id": str(selected.profile_id), "artifact_count": len(artifacts)},
            )
        as_of = datetime.now(UTC)
        unique = tuple(sorted(set(identifiers), key=str))
        async with self._sessions() as session:
            records = (
                (
                    await session.scalars(
                        select(EvidenceRecord)
                        .where(EvidenceRecord.id.in_(unique))
                        .order_by(EvidenceRecord.id)
                    )
                ).all()
                if unique
                else []
            )
            if {row.id for row in records} != set(unique):
                raise ValueError("ANALYSIS_EVIDENCE_NOT_FOUND")
            evidence = []
            for row in records:
                if row.instrument_id not in {None, queued.command.instrument_id}:
                    raise ValueError("ANALYSIS_EVIDENCE_TARGET_MISMATCH")
                freshness = derive_display_freshness(
                    as_of=as_of,
                    available_at=row.available_at,
                    expires_at=row.expires_at,
                    ingested_status=row.freshness_status,
                ).value
                if (
                    max(row.observed_at, row.effective_at, row.available_at, row.ingested_at)
                    > as_of
                ):
                    freshness = "NOT_YET_AVAILABLE"
                if row.quality_score <= Decimal(0):
                    freshness = "INVALID"
                evidence.append(
                    AnalysisEvidenceInput(
                        evidence_id=row.id,
                        instrument_id=row.instrument_id,
                        content_hash=row.content_hash,
                        source_name=row.source_name,
                        source_locator=row.source_locator,
                        source_tier=row.source_tier,
                        observed_at=row.observed_at,
                        effective_at=row.effective_at,
                        available_at=row.available_at,
                        ingested_at=row.ingested_at,
                        expires_at=row.expires_at,
                        quality_score=str(row.quality_score),
                        freshness=freshness,
                        payload_json=json.dumps(
                            row.payload_json,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    )
                )
        if sum(len(item.payload_json.encode()) for item in evidence) > 1024 * 1024:
            raise ValueError("ANALYSIS_EVIDENCE_SNAPSHOT_TOO_LARGE")
        thesis = await SqlAlchemyThesisReader(self._sessions).as_of_for_instrument(
            queued.command.instrument_id, as_of=as_of
        )
        blockers = numeric_blockers
        thesis_state = thesis.state if thesis else "UNKNOWN"
        thesis_json = (
            json.dumps(asdict(thesis), default=str, ensure_ascii=False, sort_keys=True)
            if thesis
            else None
        )
        eligible = {item.evidence_id for item in evidence if item.freshness == "FRESH"}
        if thesis and not set(thesis.evidence_ids) <= eligible:
            thesis_state = "UNKNOWN"
            thesis_json = None
            blockers.append("THESIS_EVIDENCE_NOT_IN_FROZEN_INPUT")
        value = AnalysisFrozenInput(
            run_id=run_id,
            as_of=as_of,
            instrument_id=queued.command.instrument_id,
            queued=queued,
            evidence=tuple(evidence),
            thesis_version_id=thesis.version_id if thesis else None,
            thesis_state=thesis_state,
            thesis_json=thesis_json,
            numeric_source=numeric_source,
            input_hash="",
            blockers=tuple(blockers),
        )
        return value.model_copy(
            update={
                "input_hash": fingerprint(value.model_dump(mode="json", exclude={"input_hash"}))
            }
        )
