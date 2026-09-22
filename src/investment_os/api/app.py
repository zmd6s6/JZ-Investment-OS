"""Bootstrap API with liveness and real infrastructure readiness endpoints."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime

from investment_os.application.health import AsyncClosable, ReadinessProbe
from investment_os.application.llm_budget import LLMBudgetPolicy, LLMBudgetService
from investment_os.application.onboarding import OnboardingService
from investment_os.application.provider_settings import (
    DataProviderProfile,
    ModelProviderConnectionTester,
    ModelProviderProfile,
    ProviderSettingsService,
    ProviderTestResult,
    RoleModelAssignment,
    SystemSettings,
)
from investment_os.application.research import ResearchArtifactDTO
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.database import (
    DatabaseReadinessProbe,
    create_database_engine,
    create_session_factory,
)
from investment_os.infrastructure.decision_journal import (
    DecisionJournalRead,
    SqlAlchemyDecisionJournalReader,
)
from investment_os.infrastructure.evidence_ingestion import SqlAlchemyEvidenceIngestor
from investment_os.infrastructure.report_delivery import SqlAlchemyDailyReportReader
from investment_os.infrastructure.scheduler import SqlAlchemyTaskRunReader
from investment_os.infrastructure.settings import get_settings
from investment_os.infrastructure.thesis_engine import SqlAlchemyThesisReader, ThesisVersionRead

from .schemas import (
    DailyReportResponse,
    DataProviderProfileRequest,
    DataProviderProfileResponse,
    DecisionJournalResponse,
    LivenessResponse,
    LLMBudgetPolicyRequest,
    LLMBudgetResponse,
    LLMBudgetUsageResponse,
    ModelProviderProfileRequest,
    ModelProviderProfileResponse,
    OnboardingStateResponse,
    ProductCapabilityResponse,
    ProviderTestResponse,
    ReadinessResponse,
    ResearchIngestRequest,
    ResearchIngestResponse,
    RoleModelAssignmentRequest,
    RoleModelAssignmentResponse,
    SystemSettingsResponse,
    SystemSettingsUpdateRequest,
    TaskRunResponse,
    ThesisHistoryResponse,
    ThesisVersionResponse,
)


def _thesis_response(version: ThesisVersionRead) -> ThesisVersionResponse:
    return ThesisVersionResponse.model_validate(
        {
            "instrument_id": version.instrument_id,
            "thesis_id": version.thesis_id,
            "version_id": version.version_id,
            "version": version.version,
            "parent_version_id": version.parent_version_id,
            "state": version.state,
            "long_term_summary": version.summary,
            "pillars": version.pillars,
            "catalysts": version.catalysts,
            "risks": version.risks,
            "invalidation_conditions": version.invalidation_conditions,
            "monitoring_conditions": version.monitoring_conditions,
            "change_reason": version.change_reason,
            "evidence_ids": version.evidence_ids,
            "created_at": version.created_at,
        }
    )


def _decision_journal_response(journal: DecisionJournalRead) -> DecisionJournalResponse:
    return DecisionJournalResponse.model_validate(
        {
            "decision_id": journal.decision_id,
            "instrument_id": journal.instrument_id,
            "portfolio_id": journal.portfolio_id,
            "committee_session_id": journal.committee_session_id,
            "thesis_version_id": journal.thesis_version_id,
            "policy_version_id": journal.policy_version_id,
            "strategy_version_id": journal.strategy_version_id,
            "risk_assessment_id": journal.risk_assessment_id,
            "position_sizing_run_id": journal.position_sizing_run_id,
            "action": journal.action,
            "confidence": journal.confidence,
            "risk_intent": journal.risk_intent,
            "core_action": journal.core_action,
            "tactical_action": journal.tactical_action,
            "state": journal.state,
            "reasons": journal.reasons,
            "risks": journal.risks,
            "watch_conditions": journal.watch_conditions,
            "invalidation_conditions": journal.invalidation_conditions,
            "position_before": journal.position_before,
            "position_after_proposed": journal.position_after_proposed,
            "unknowns": journal.unknowns,
            "dissent": journal.dissent,
            "next_review_at": journal.next_review_at,
            "input_snapshot_hash": journal.input_snapshot_hash,
            "prompt_bundle_version": journal.prompt_bundle_version,
            "formula_version": journal.formula_version,
            "content_hash": journal.content_hash,
            "version": journal.version,
            "evidence_ids": journal.evidence_ids,
            "approvals": [
                {
                    "id": approval.id,
                    "actor_id": approval.actor_id,
                    "action": approval.action,
                    "comment": approval.comment,
                    "expires_at": approval.expires_at,
                    "occurred_at": approval.occurred_at,
                }
                for approval in journal.approvals
            ],
            "executions": [
                {
                    "id": execution.id,
                    "approval_id": execution.approval_id,
                    "execution_mode": execution.execution_mode,
                    "status": execution.status,
                    "requested_quantity": execution.requested_quantity,
                    "filled_quantity": execution.filled_quantity,
                    "avg_price": execution.avg_price,
                    "external_refs": execution.external_refs,
                    "occurred_at": execution.occurred_at,
                }
                for execution in journal.executions
            ],
            "created_at": journal.created_at,
        }
    )


def _system_settings_response(settings: SystemSettings) -> SystemSettingsResponse:
    return SystemSettingsResponse(
        market_timezone=settings.market_timezone,
        market_scopes=list(settings.market_scopes),
        auto_trade=False,
    )


def _model_profile_response(profile: ModelProviderProfile) -> ModelProviderProfileResponse:
    return ModelProviderProfileResponse(
        id=profile.id,
        name=profile.name,
        provider_type=profile.provider_type,
        base_url=profile.base_url,
        model_name=profile.model_name,
        timeout_seconds=profile.timeout_seconds,
        max_tokens=profile.max_tokens,
        enabled=profile.enabled,
        credential_configured=profile.credential_ref is not None,
        pricing_version=profile.pricing_version,
        pricing_currency=profile.pricing_currency,
        input_token_price=profile.input_token_price,
        output_token_price=profile.output_token_price,
        pricing_effective_at=profile.pricing_effective_at,
    )


def _data_profile_response(profile: DataProviderProfile) -> DataProviderProfileResponse:
    return DataProviderProfileResponse(
        id=profile.id,
        name=profile.name,
        provider_type=profile.provider_type,
        base_url=profile.base_url,
        timeout_seconds=profile.timeout_seconds,
        enabled=profile.enabled,
        credential_configured=profile.credential_ref is not None,
    )


def _role_assignment_response(assignment: RoleModelAssignment) -> RoleModelAssignmentResponse:
    return RoleModelAssignmentResponse(
        role=assignment.role,
        model_provider_profile_id=assignment.model_provider_profile_id,
    )


async def _save_model_provider(
    service: ProviderSettingsService,
    profile_id: UUID | None,
    request: ModelProviderProfileRequest,
) -> ModelProviderProfile:
    try:
        return await service.save_model_profile(
            profile_id=profile_id,
            name=request.name,
            provider_type=request.provider_type,
            base_url=request.base_url,
            model_name=request.model_name,
            timeout_seconds=request.timeout_seconds,
            max_tokens=request.max_tokens,
            enabled=request.enabled,
            credential=(
                request.credential.get_secret_value() if request.credential is not None else None
            ),
            pricing_version=request.pricing_version,
            pricing_currency=request.pricing_currency,
            input_token_price=request.input_token_price,
            output_token_price=request.output_token_price,
            pricing_effective_at=request.pricing_effective_at,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="secret_store_unavailable") from exc


async def _save_data_provider(
    service: ProviderSettingsService,
    profile_id: UUID | None,
    request: DataProviderProfileRequest,
) -> DataProviderProfile:
    try:
        return await service.save_data_profile(
            profile_id=profile_id,
            name=request.name,
            provider_type=request.provider_type,
            base_url=request.base_url,
            timeout_seconds=request.timeout_seconds,
            enabled=request.enabled,
            credential=(
                request.credential.get_secret_value() if request.credential is not None else None
            ),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="secret_store_unavailable") from exc


async def _test_model_provider(
    service: ProviderSettingsService,
    profile_id: UUID,
    connection_tester: ModelProviderConnectionTester | None,
) -> ProviderTestResult:
    try:
        return await service.test_model_profile(
            profile_id,
            connection_tester=connection_tester,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def _test_data_provider(
    service: ProviderSettingsService, profile_id: UUID
) -> ProviderTestResult:
    try:
        return await service.test_data_profile(profile_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def create_app(
    readiness_probe: ReadinessProbe | None = None,
    evidence_ingestor: SqlAlchemyEvidenceIngestor | None = None,
    thesis_reader: SqlAlchemyThesisReader | None = None,
    decision_journal_reader: SqlAlchemyDecisionJournalReader | None = None,
    task_run_reader: SqlAlchemyTaskRunReader | None = None,
    daily_report_reader: SqlAlchemyDailyReportReader | None = None,
    onboarding_service: OnboardingService | None = None,
    provider_settings_service: ProviderSettingsService | None = None,
    model_connection_tester: ModelProviderConnectionTester | None = None,
    llm_budget_service: LLMBudgetService | None = None,
    onboarding_lifecycle: AsyncClosable | None = None,
) -> FastAPI:
    """Build an application, allowing tests to inject a deterministic probe."""

    settings = get_settings()
    selected_probe = readiness_probe or DatabaseReadinessProbe(settings.database_url)
    reader_engine = None
    selected_thesis_reader = thesis_reader
    selected_decision_journal_reader = decision_journal_reader
    selected_task_run_reader = task_run_reader
    selected_daily_report_reader = daily_report_reader
    selected_onboarding_service = onboarding_service
    selected_provider_settings_service = provider_settings_service
    selected_model_connection_tester = model_connection_tester
    selected_llm_budget_service = llm_budget_service
    if (
        selected_thesis_reader is None
        or selected_decision_journal_reader is None
        or selected_task_run_reader is None
        or selected_daily_report_reader is None
    ):
        reader_engine = create_database_engine(settings.database_url)
        session_factory = create_session_factory(reader_engine)
        if selected_thesis_reader is None:
            selected_thesis_reader = SqlAlchemyThesisReader(session_factory)
        if selected_decision_journal_reader is None:
            selected_decision_journal_reader = SqlAlchemyDecisionJournalReader(session_factory)
        if selected_task_run_reader is None:
            selected_task_run_reader = SqlAlchemyTaskRunReader(session_factory)
        if selected_daily_report_reader is None:
            selected_daily_report_reader = SqlAlchemyDailyReportReader(session_factory)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if isinstance(selected_probe, AsyncClosable):
            await selected_probe.close()
        if reader_engine is not None:
            await reader_engine.dispose()
        if onboarding_lifecycle is not None:
            await onboarding_lifecycle.close()
        if isinstance(selected_model_connection_tester, AsyncClosable):
            await selected_model_connection_tester.close()

    application = FastAPI(
        title="Personal AI Investment OS",
        version="0.1.0",
        description="Evidence-backed research ingestion plus immutable Thesis and Decision Journal "
        "read APIs; no execution.",
        lifespan=lifespan,
    )

    @application.get("/health/live", response_model=LivenessResponse, tags=["health"])
    async def liveness() -> LivenessResponse:
        return LivenessResponse()

    @application.get(
        "/health/ready",
        response_model=ReadinessResponse,
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
        tags=["health"],
    )
    async def readiness(response: Response) -> ReadinessResponse:
        check = await selected_probe.check()
        if not check.ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="ready" if check.ready else "not_ready",
            checks={"database": check.detail},
        )

    @application.get(
        "/api/v1/onboarding", response_model=OnboardingStateResponse, tags=["onboarding"]
    )
    async def onboarding_state() -> OnboardingStateResponse:
        if selected_onboarding_service is None:
            raise HTTPException(status_code=503, detail="onboarding_unavailable")
        return OnboardingStateResponse.model_validate(
            await selected_onboarding_service.current_state(), from_attributes=True
        )

    @application.post(
        "/api/v1/onboarding/start", response_model=OnboardingStateResponse, tags=["onboarding"]
    )
    async def start_onboarding() -> OnboardingStateResponse:
        if selected_onboarding_service is None:
            raise HTTPException(status_code=503, detail="onboarding_unavailable")
        return OnboardingStateResponse.model_validate(
            await selected_onboarding_service.start(), from_attributes=True
        )

    @application.get(
        "/api/v1/product-capabilities",
        response_model=list[ProductCapabilityResponse],
        tags=["product"],
        description=(
            "返回服务端定义的当前能力状态。尚未具备受审查配置路径的能力必须标记为 "
            "NOT_IMPLEMENTED, 而不是 CONFIGURATION_REQUIRED。"
        ),
    )
    async def product_capabilities() -> list[ProductCapabilityResponse]:
        return [
            ProductCapabilityResponse(
                key="onboarding",
                label="首次配置向导",
                status="AVAILABLE",
                detail="可记录首次配置已开始, 不收集密钥或真实持仓。",
            ),
            ProductCapabilityResponse(
                key="providers",
                label="模型与数据提供方",
                status=(
                    "CONFIGURATION_REQUIRED"
                    if selected_provider_settings_service is not None
                    else "NOT_IMPLEMENTED"
                ),
                detail=(
                    "可安全配置提供方档案。模型连接测试会在所有者明确发起后执行。"
                    "并检查认证和结构化输出。"
                    if selected_model_connection_tester is not None
                    else "可安全配置提供方档案。当前部署仅提供无网络配置校验。"
                    if selected_provider_settings_service is not None
                    else "PRODUCT-02 才会提供受审查的密钥存储与配置能力。"
                ),
            ),
            ProductCapabilityResponse(
                key="portfolio",
                label="资产组合导入",
                status="NOT_IMPLEMENTED",
                detail="尚不接受真实持仓录入或导入。",
            ),
            ProductCapabilityResponse(
                key="execution",
                label="实盘执行",
                status="NOT_IMPLEMENTED",
                detail="V1 始终禁止自动交易和券商下单。",
            ),
        ]

    def provider_settings_or_503() -> ProviderSettingsService:
        if selected_provider_settings_service is None:
            raise HTTPException(status_code=503, detail="provider_settings_unavailable")
        return selected_provider_settings_service

    def llm_budget_or_503() -> LLMBudgetService:
        if selected_llm_budget_service is None:
            raise HTTPException(status_code=503, detail="llm_budget_unavailable")
        return selected_llm_budget_service

    @application.get(
        "/api/v1/settings/system",
        response_model=SystemSettingsResponse,
        tags=["settings"],
    )
    async def read_system_settings() -> SystemSettingsResponse:
        return _system_settings_response(await provider_settings_or_503().system_settings())

    @application.put(
        "/api/v1/settings/system",
        response_model=SystemSettingsResponse,
        tags=["settings"],
    )
    async def update_system_settings(
        request: SystemSettingsUpdateRequest,
    ) -> SystemSettingsResponse:
        try:
            settings = await provider_settings_or_503().save_system_settings(
                market_timezone=request.market_timezone,
                market_scopes=tuple(request.market_scopes),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _system_settings_response(settings)

    @application.get(
        "/api/v1/settings/model-providers",
        response_model=list[ModelProviderProfileResponse],
        tags=["settings"],
    )
    async def list_model_providers() -> list[ModelProviderProfileResponse]:
        return [
            _model_profile_response(profile)
            for profile in await provider_settings_or_503().list_model_profiles()
        ]

    @application.post(
        "/api/v1/settings/model-providers",
        response_model=ModelProviderProfileResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["settings"],
    )
    async def create_model_provider(
        request: ModelProviderProfileRequest,
    ) -> ModelProviderProfileResponse:
        return _model_profile_response(
            await _save_model_provider(provider_settings_or_503(), None, request)
        )

    @application.get(
        "/api/v1/settings/model-providers/{profile_id}",
        response_model=ModelProviderProfileResponse,
        tags=["settings"],
    )
    async def read_model_provider(profile_id: UUID) -> ModelProviderProfileResponse:
        profile = await provider_settings_or_503().get_model_profile(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="model_provider_not_found")
        return _model_profile_response(profile)

    @application.put(
        "/api/v1/settings/model-providers/{profile_id}",
        response_model=ModelProviderProfileResponse,
        tags=["settings"],
    )
    async def update_model_provider(
        profile_id: UUID, request: ModelProviderProfileRequest
    ) -> ModelProviderProfileResponse:
        return _model_profile_response(
            await _save_model_provider(provider_settings_or_503(), profile_id, request)
        )

    @application.delete(
        "/api/v1/settings/model-providers/{profile_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["settings"],
    )
    async def delete_model_provider(profile_id: UUID) -> Response:
        try:
            deleted = await provider_settings_or_503().delete_model_profile(profile_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="model_provider_not_found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.post(
        "/api/v1/settings/model-providers/{profile_id}/test",
        response_model=ProviderTestResponse,
        tags=["settings"],
    )
    async def test_model_provider(profile_id: UUID) -> ProviderTestResponse:
        result = await _test_model_provider(
            provider_settings_or_503(),
            profile_id,
            selected_model_connection_tester,
        )
        return ProviderTestResponse(
            status=result.status,
            detail=result.detail,
            latency_ms=result.latency_ms,
        )

    @application.get(
        "/api/v1/settings/data-providers",
        response_model=list[DataProviderProfileResponse],
        tags=["settings"],
    )
    async def list_data_providers() -> list[DataProviderProfileResponse]:
        return [
            _data_profile_response(profile)
            for profile in await provider_settings_or_503().list_data_profiles()
        ]

    @application.post(
        "/api/v1/settings/data-providers",
        response_model=DataProviderProfileResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["settings"],
    )
    async def create_data_provider(
        request: DataProviderProfileRequest,
    ) -> DataProviderProfileResponse:
        return _data_profile_response(
            await _save_data_provider(provider_settings_or_503(), None, request)
        )

    @application.get(
        "/api/v1/settings/data-providers/{profile_id}",
        response_model=DataProviderProfileResponse,
        tags=["settings"],
    )
    async def read_data_provider(profile_id: UUID) -> DataProviderProfileResponse:
        profile = await provider_settings_or_503().get_data_profile(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="data_provider_not_found")
        return _data_profile_response(profile)

    @application.put(
        "/api/v1/settings/data-providers/{profile_id}",
        response_model=DataProviderProfileResponse,
        tags=["settings"],
    )
    async def update_data_provider(
        profile_id: UUID, request: DataProviderProfileRequest
    ) -> DataProviderProfileResponse:
        return _data_profile_response(
            await _save_data_provider(provider_settings_or_503(), profile_id, request)
        )

    @application.delete(
        "/api/v1/settings/data-providers/{profile_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["settings"],
    )
    async def delete_data_provider(profile_id: UUID) -> Response:
        deleted = await provider_settings_or_503().delete_data_profile(profile_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="data_provider_not_found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.post(
        "/api/v1/settings/data-providers/{profile_id}/test",
        response_model=ProviderTestResponse,
        tags=["settings"],
    )
    async def test_data_provider(profile_id: UUID) -> ProviderTestResponse:
        result = await _test_data_provider(provider_settings_or_503(), profile_id)
        return ProviderTestResponse(status=result.status, detail=result.detail)

    @application.get(
        "/api/v1/settings/role-model-assignments",
        response_model=list[RoleModelAssignmentResponse],
        tags=["settings"],
    )
    async def list_role_model_assignments() -> list[RoleModelAssignmentResponse]:
        return [
            _role_assignment_response(assignment)
            for assignment in await provider_settings_or_503().list_role_assignments()
        ]

    @application.put(
        "/api/v1/settings/role-model-assignments/{role}",
        response_model=RoleModelAssignmentResponse,
        tags=["settings"],
    )
    async def save_role_model_assignment(
        role: str, request: RoleModelAssignmentRequest
    ) -> RoleModelAssignmentResponse:
        try:
            assignment = await provider_settings_or_503().save_role_assignment(
                role=role, model_provider_profile_id=request.model_provider_profile_id
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _role_assignment_response(assignment)

    @application.delete(
        "/api/v1/settings/role-model-assignments/{role}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["settings"],
    )
    async def delete_role_model_assignment(role: str) -> Response:
        try:
            deleted = await provider_settings_or_503().delete_role_assignment(role)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="role_model_assignment_not_found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.get(
        "/api/v1/settings/llm-budget", response_model=LLMBudgetResponse, tags=["settings"]
    )
    async def read_llm_budget() -> LLMBudgetResponse:
        service = llm_budget_or_503()
        policy = await service.policy()
        if policy is None:
            return LLMBudgetResponse(status="NOT_CONFIGURED")
        usage = await service.usage()
        return LLMBudgetResponse(
            status="CONFIGURED",
            version=policy.version,
            currency=policy.currency,
            task_token_limit=policy.task_token_limit,
            daily_token_limit=policy.daily_token_limit,
            task_cost_limit=policy.task_cost_limit,
            daily_cost_limit=policy.daily_cost_limit,
            usage=LLMBudgetUsageResponse(
                window_date=usage.window_date.isoformat(),
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_cost=usage.total_cost,
                reserved_tokens=usage.reserved_tokens,
                reserved_cost=usage.reserved_cost,
                remaining_tokens=usage.remaining_tokens,
                remaining_cost=usage.remaining_cost,
            )
            if usage
            else None,
        )

    @application.put(
        "/api/v1/settings/llm-budget", response_model=LLMBudgetResponse, tags=["settings"]
    )
    async def save_llm_budget(request: LLMBudgetPolicyRequest) -> LLMBudgetResponse:
        try:
            await llm_budget_or_503().save_policy(
                LLMBudgetPolicy(
                    request.version,
                    request.currency,
                    request.task_token_limit,
                    request.daily_token_limit,
                    request.task_cost_limit,
                    request.daily_cost_limit,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return await read_llm_budget()

    @application.post(
        "/api/v1/research/ingest", response_model=ResearchIngestResponse, tags=["research"]
    )
    async def ingest(request: ResearchIngestRequest) -> ResearchIngestResponse:
        if evidence_ingestor is None:
            raise HTTPException(status_code=503, detail="research_ingestion_unavailable")
        artifact = ResearchArtifactDTO(
            provider=request.provider,
            provider_ref=request.provider_ref,
            artifact_type=request.artifact_type,
            source_name=request.source_name,
            source_locator=request.source_locator,
            source_tier=request.source_tier,
            observed_at=UtcTimestamp(request.observed_at),
            effective_at=UtcTimestamp(request.effective_at),
            available_at=UtcTimestamp(request.available_at),
            payload=request.payload,
            source_schema_version=request.source_schema_version,
            instrument_id=request.instrument_id,
            expires_at=UtcTimestamp(request.expires_at) if request.expires_at else None,
            supersedes_id=request.supersedes_id,
        )
        result = await evidence_ingestor.ingest(artifact)
        return ResearchIngestResponse(evidence_id=result.evidence_id, reused=result.reused)

    @application.get(
        "/api/v1/theses/{instrument_id}", response_model=ThesisVersionResponse, tags=["theses"]
    )
    async def read_thesis(
        instrument_id: UUID,
        as_of: AwareDatetime | None = None,
    ) -> ThesisVersionResponse:
        version = (
            await selected_thesis_reader.current_for_instrument(instrument_id)
            if as_of is None
            else await selected_thesis_reader.as_of_for_instrument(instrument_id, as_of=as_of)
        )
        if version is None:
            raise HTTPException(status_code=404, detail="thesis_not_found")
        return _thesis_response(version)

    @application.get(
        "/api/v1/theses/{instrument_id}/versions",
        response_model=ThesisHistoryResponse,
        tags=["theses"],
    )
    async def thesis_history(instrument_id: UUID) -> ThesisHistoryResponse:
        versions = await selected_thesis_reader.history_for_instrument(instrument_id)
        if not versions:
            raise HTTPException(status_code=404, detail="thesis_not_found")
        return ThesisHistoryResponse(
            instrument_id=instrument_id,
            versions=[_thesis_response(version) for version in versions],
        )

    @application.get(
        "/api/v1/decisions/{decision_id}",
        response_model=DecisionJournalResponse,
        tags=["decisions"],
    )
    async def read_decision_journal(decision_id: UUID) -> DecisionJournalResponse:
        journal = await selected_decision_journal_reader.get(decision_id)
        if journal is None:
            raise HTTPException(status_code=404, detail="decision_not_found")
        return _decision_journal_response(journal)

    @application.get("/api/v1/task-runs", response_model=list[TaskRunResponse], tags=["jobs"])
    async def list_task_runs(limit: int = Query(default=50, ge=1, le=100)) -> list[TaskRunResponse]:
        try:
            runs = await selected_task_run_reader.list_recent(limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return [TaskRunResponse.model_validate(run, from_attributes=True) for run in runs]

    @application.get(
        "/api/v1/reports/daily/latest", response_model=DailyReportResponse, tags=["reports"]
    )
    async def latest_daily_report() -> DailyReportResponse:
        try:
            report = await selected_daily_report_reader.latest()
        except ValueError as exc:
            raise HTTPException(status_code=503, detail="daily_report_unavailable") from exc
        if report is None:
            raise HTTPException(status_code=404, detail="daily_report_not_found")
        return DailyReportResponse.model_validate(report, from_attributes=True)

    @application.get("/api/v1/reports/daily", response_model=DailyReportResponse, tags=["reports"])
    async def daily_report_as_of(as_of: AwareDatetime) -> DailyReportResponse:
        try:
            report = await selected_daily_report_reader.as_of(as_of)
        except ValueError as exc:
            raise HTTPException(status_code=503, detail="daily_report_unavailable") from exc
        if report is None:
            raise HTTPException(status_code=404, detail="daily_report_not_found")
        return DailyReportResponse.model_validate(report, from_attributes=True)

    frontend_dist = Path(__file__).resolve().parents[3] / "web" / "dist"
    if frontend_dist.is_dir():
        application.mount(
            "/assets", StaticFiles(directory=frontend_dist / "assets"), name="web-assets"
        )

        @application.get("/", include_in_schema=False)
        async def personal_ui() -> FileResponse:
            return FileResponse(frontend_dist / "index.html")

        @application.get("/settings", include_in_schema=False)
        async def settings_ui() -> FileResponse:
            """Serve the same SPA entry point for the supported P2 settings route."""

            return FileResponse(frontend_dist / "index.html")

    return application
