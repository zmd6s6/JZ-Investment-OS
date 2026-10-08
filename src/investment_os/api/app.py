"""Bootstrap API with liveness and real infrastructure readiness endpoints."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime
from sqlalchemy import select

from investment_os.application.health import AsyncClosable, ReadinessProbe
from investment_os.application.instrument_catalog import InstrumentCatalogService
from investment_os.application.llm_budget import LLMBudgetPolicy, LLMBudgetService
from investment_os.application.onboarding import OnboardingService
from investment_os.application.portfolio_book import (
    PortfolioBookService,
    PortfolioPositionInput,
    PortfolioView,
)
from investment_os.application.portfolio_csv import (
    CsvImportPreview,
    CsvRowResult,
    PortfolioCsvImportService,
)
from investment_os.application.provider_settings import (
    DataProviderConnectionTester,
    DataProviderProfile,
    ModelProviderConnectionTester,
    ModelProviderProfile,
    ProviderSettingsService,
    ProviderTestResult,
    RoleModelAssignment,
    SystemSettings,
)
from investment_os.application.research import (
    ResearchArtifactDTO,
    ResearchProviderSchemaError,
    ResearchProviderUnavailableError,
    ResearchRequest,
)
from investment_os.application.research_runtime import ResearchProviderRuntime, ResearchRuntimeError
from investment_os.application.watchlist import WatchlistService
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.catalog_portfolio import (
    SessionCatalogPort,
    SessionPortfolioBookPort,
    SessionWatchlistPort,
)
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
    CsvImportCommitResponse,
    CsvImportPreviewResponse,
    CsvImportRequest,
    CsvRowResultResponse,
    DailyReportResponse,
    DataProviderProfileRequest,
    DataProviderProfileResponse,
    DecisionJournalResponse,
    InstrumentCatalogResponse,
    InstrumentIdentityRequest,
    LivenessResponse,
    LLMBudgetPolicyRequest,
    LLMBudgetResponse,
    LLMBudgetUsageResponse,
    ManualPositionRequest,
    ModelProviderProfileRequest,
    ModelProviderProfileResponse,
    OnboardingStateResponse,
    PolicyReviewResponse,
    PortfolioCashUpdateRequest,
    PortfolioCreateRequest,
    PortfolioResponse,
    ProductCapabilityResponse,
    ProviderResearchFetchRequest,
    ProviderResearchFetchResponse,
    ProviderSyncHistoryResponse,
    ProviderTestHistoryResponse,
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
    WatchlistItemResponse,
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
        retention_days=profile.retention_days,
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
            retention_days=request.retention_days,
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
    service: ProviderSettingsService,
    profile_id: UUID,
    connection_tester: DataProviderConnectionTester | None,
) -> ProviderTestResult:
    try:
        return await service.test_data_profile(profile_id, connection_tester=connection_tester)
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
    data_connection_tester: DataProviderConnectionTester | None = None,
    research_provider_runtime: ResearchProviderRuntime | None = None,
    llm_budget_service: LLMBudgetService | None = None,
    onboarding_lifecycle: AsyncClosable | None = None,
    instrument_catalog_service: InstrumentCatalogService | None = None,
    portfolio_book_service: PortfolioBookService | None = None,
    watchlist_service: WatchlistService | None = None,
    portfolio_csv_service: PortfolioCsvImportService | None = None,
    write_api_token: str | None = None,
) -> FastAPI:
    """Build an application, allowing tests to inject a deterministic probe."""

    settings = get_settings()
    selected_probe = readiness_probe or DatabaseReadinessProbe(settings.database_url)
    reader_engine = None
    session_factory = None
    selected_thesis_reader = thesis_reader
    selected_decision_journal_reader = decision_journal_reader
    selected_task_run_reader = task_run_reader
    selected_daily_report_reader = daily_report_reader
    selected_onboarding_service = onboarding_service
    selected_provider_settings_service = provider_settings_service
    selected_model_connection_tester = model_connection_tester
    selected_data_connection_tester = data_connection_tester
    selected_research_provider_runtime = research_provider_runtime
    selected_llm_budget_service = llm_budget_service
    selected_instrument_catalog_service = instrument_catalog_service
    selected_portfolio_book_service = portfolio_book_service
    selected_watchlist_service = watchlist_service
    selected_portfolio_csv_service = portfolio_csv_service
    if (
        selected_thesis_reader is None
        or selected_decision_journal_reader is None
        or selected_task_run_reader is None
        or selected_daily_report_reader is None
        or selected_instrument_catalog_service is None
        or selected_portfolio_book_service is None
        or selected_watchlist_service is None
        or selected_portfolio_csv_service is None
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
        if selected_instrument_catalog_service is None:
            selected_instrument_catalog_service = InstrumentCatalogService(
                SessionCatalogPort(session_factory)
            )
        if selected_portfolio_book_service is None:
            selected_portfolio_book_service = PortfolioBookService(
                SessionPortfolioBookPort(session_factory),
                SessionCatalogPort(session_factory),
            )
        if selected_portfolio_csv_service is None and selected_portfolio_book_service is not None:
            selected_portfolio_csv_service = PortfolioCsvImportService(
                selected_portfolio_book_service,
                SessionCatalogPort(session_factory),
            )
        if selected_watchlist_service is None:
            selected_watchlist_service = WatchlistService(
                SessionWatchlistPort(session_factory),
                SessionCatalogPort(session_factory),
            )

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
        if isinstance(selected_data_connection_tester, AsyncClosable):
            await selected_data_connection_tester.close()

    application = FastAPI(
        title="Personal AI Investment OS",
        version="0.1.0",
        description="Evidence-backed research ingestion plus immutable Thesis and Decision Journal "
        "read APIs; no execution.",
        lifespan=lifespan,
    )
    from investment_os.api.write_auth import WriteApiAuthMiddleware

    selected_write_token = (
        write_api_token if write_api_token is not None else settings.api_write_token
    )
    application.add_middleware(WriteApiAuthMiddleware, token=selected_write_token)

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
                status="CONFIGURATION_REQUIRED",
                detail="P5 支持手工持仓与本地 Instrument 目录. CSV 与对账仍在推进. 不伪造市值.",
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

    def research_provider_runtime_or_503() -> ResearchProviderRuntime:
        if selected_research_provider_runtime is None:
            raise HTTPException(status_code=503, detail="research_provider_runtime_unavailable")
        return selected_research_provider_runtime

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
        result = await _test_data_provider(
            provider_settings_or_503(),
            profile_id,
            selected_data_connection_tester,
        )
        return ProviderTestResponse(
            status=result.status,
            detail=result.detail,
            latency_ms=result.latency_ms,
        )

    @application.get(
        "/api/v1/settings/data-providers/{profile_id}/last-test",
        response_model=ProviderTestHistoryResponse | None,
        tags=["settings"],
    )
    async def read_last_data_provider_test(
        profile_id: UUID,
    ) -> ProviderTestHistoryResponse | None:
        try:
            latest = await provider_settings_or_503().latest_data_provider_test(profile_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if latest is None:
            return None
        return ProviderTestHistoryResponse(
            status=latest.status,
            occurred_at=latest.occurred_at,
            latency_ms=latest.latency_ms,
        )

    @application.get(
        "/api/v1/settings/data-providers/{profile_id}/last-sync",
        response_model=ProviderSyncHistoryResponse | None,
        tags=["settings"],
    )
    async def read_last_data_provider_sync(profile_id: UUID) -> ProviderSyncHistoryResponse | None:
        try:
            latest = await provider_settings_or_503().latest_data_provider_sync(profile_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if latest is None:
            return None
        return ProviderSyncHistoryResponse(
            occurred_at=latest.occurred_at,
            artifact_count=latest.artifact_count,
            latency_ms=latest.latency_ms,
        )

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

    @application.post(
        "/api/v1/research/providers/{profile_id}/fetch",
        response_model=ProviderResearchFetchResponse,
        tags=["research"],
        description=("仅按明确指定的已启用提供方档案获取研究线索, 不会自动回退到其他来源。"),
    )
    async def fetch_provider_research(
        profile_id: UUID, request: ProviderResearchFetchRequest
    ) -> ProviderResearchFetchResponse:
        if evidence_ingestor is None:
            raise HTTPException(status_code=503, detail="research_ingestion_unavailable")
        started = monotonic()
        try:
            artifacts = await research_provider_runtime_or_503().fetch(
                profile_id=profile_id,
                request=ResearchRequest(
                    instrument_ids=tuple(request.instrument_ids),
                    as_of=UtcTimestamp(request.as_of),
                    query=request.query,
                    max_results=request.max_results,
                ),
            )
        except ResearchProviderUnavailableError as exc:
            raise HTTPException(status_code=502, detail="research_provider_unavailable") from exc
        except (ResearchRuntimeError, ResearchProviderSchemaError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail="research_provider_request_rejected"
            ) from exc
        correlation_id = uuid4()
        results: list[ResearchIngestResponse] = []
        for artifact in artifacts:
            result = await evidence_ingestor.ingest(artifact, correlation_id=correlation_id)
            results.append(
                ResearchIngestResponse(evidence_id=result.evidence_id, reused=result.reused)
            )
        if selected_provider_settings_service is not None:
            await selected_provider_settings_service.record_data_provider_sync(
                profile_id=profile_id,
                artifact_count=len(results),
                latency_ms=int((monotonic() - started) * 1000),
            )
        return ProviderResearchFetchResponse(provider_profile_id=profile_id, results=results)

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

    def _portfolio_response(view: PortfolioView) -> PortfolioResponse:
        from datetime import datetime

        return PortfolioResponse(
            portfolio_id=view.portfolio_id,
            name=view.name,
            base_currency=view.base_currency,
            cash_balance=view.cash_balance,
            status=view.status,
            as_of=datetime.now(UTC),
            missing_pricing=True,
            positions=[
                {
                    "position_id": position.position_id,
                    "instrument_id": position.instrument_id,
                    "market": position.market,
                    "symbol": position.symbol,
                    "name": position.name,
                    "asset_type": position.asset_type,
                    "currency": position.currency,
                    "sector": position.sector,
                    "core_quantity": position.core_quantity,
                    "tactical_quantity": position.tactical_quantity,
                    "average_cost": position.average_cost,
                    "core_average_cost": position.core_average_cost,
                    "tactical_average_cost": position.tactical_average_cost,
                    "core_reason": position.core_reason,
                    "tactical_reason": position.tactical_reason,
                    "operation": position.operation,
                }
                for position in view.positions
            ],
        )

    @application.get(
        "/api/v1/instruments/search",
        response_model=list[InstrumentCatalogResponse],
        tags=["instruments"],
    )
    async def search_instruments(
        q: str = Query(min_length=1, max_length=128),
        limit: int = Query(default=20, ge=1, le=50),
    ) -> list[InstrumentCatalogResponse]:
        entries = await selected_instrument_catalog_service.search(q, limit=limit)
        return [
            InstrumentCatalogResponse.model_validate(entry, from_attributes=True)
            for entry in entries
        ]

    @application.post(
        "/api/v1/instruments",
        response_model=InstrumentCatalogResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["instruments"],
    )
    async def register_instrument(request: InstrumentIdentityRequest) -> InstrumentCatalogResponse:
        from investment_os.application.errors import ApplicationError
        from investment_os.domain.instrument import InstrumentIdentity

        try:
            identity = InstrumentIdentity(
                market=request.market,
                symbol=request.symbol,
                name=request.name,
                asset_type=request.asset_type,
                currency=request.currency,
                sector=request.sector,
            )
            entry = await selected_instrument_catalog_service.register(identity)
        except ApplicationError as exc:
            raise HTTPException(status_code=422, detail=exc.code.value) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail="instrument_identity_invalid") from exc
        return InstrumentCatalogResponse.model_validate(entry, from_attributes=True)

    @application.get(
        "/api/v1/portfolios",
        response_model=list[PortfolioResponse],
        tags=["portfolio"],
    )
    async def list_portfolios() -> list[PortfolioResponse]:
        views = await selected_portfolio_book_service.list_portfolios()
        return [_portfolio_response(view) for view in views]

    @application.post(
        "/api/v1/portfolios",
        response_model=PortfolioResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["portfolio"],
    )
    async def create_portfolio(request: PortfolioCreateRequest) -> PortfolioResponse:
        from investment_os.application.errors import ApplicationError

        try:
            view = await selected_portfolio_book_service.create_portfolio(
                name=request.name,
                base_currency=request.base_currency,
                cash_balance=request.cash_balance,
            )
        except ApplicationError as exc:
            raise HTTPException(status_code=422, detail=exc.code.value) from exc
        return _portfolio_response(view)

    @application.get(
        "/api/v1/portfolios/{portfolio_id}",
        response_model=PortfolioResponse,
        tags=["portfolio"],
    )
    async def get_portfolio(portfolio_id: UUID) -> PortfolioResponse:
        from investment_os.application.errors import ApplicationError, ApplicationErrorCode

        try:
            view = await selected_portfolio_book_service.get_portfolio(portfolio_id)
        except ApplicationError as exc:
            if exc.code is ApplicationErrorCode.PORTFOLIO_NOT_FOUND:
                raise HTTPException(status_code=404, detail=exc.code.value) from exc
            raise HTTPException(status_code=422, detail=exc.code.value) from exc
        return _portfolio_response(view)

    @application.put(
        "/api/v1/portfolios/{portfolio_id}/cash",
        response_model=PortfolioResponse,
        tags=["portfolio"],
    )
    async def set_portfolio_cash(
        portfolio_id: UUID, request: PortfolioCashUpdateRequest
    ) -> PortfolioResponse:
        from investment_os.application.errors import ApplicationError, ApplicationErrorCode

        try:
            view = await selected_portfolio_book_service.set_cash_balance(
                portfolio_id, request.cash_balance
            )
        except ApplicationError as exc:
            if exc.code is ApplicationErrorCode.PORTFOLIO_NOT_FOUND:
                raise HTTPException(status_code=404, detail=exc.code.value) from exc
            raise HTTPException(status_code=422, detail=exc.code.value) from exc
        return _portfolio_response(view)

    @application.post(
        "/api/v1/portfolios/{portfolio_id}/positions",
        response_model=PortfolioResponse,
        tags=["portfolio"],
    )
    async def record_manual_position(
        portfolio_id: UUID, request: ManualPositionRequest
    ) -> PortfolioResponse:
        from investment_os.application.errors import ApplicationError, ApplicationErrorCode

        try:
            view = await selected_portfolio_book_service.record_manual_position(
                portfolio_id=portfolio_id,
                position=PortfolioPositionInput(
                    market=request.market,
                    symbol=request.symbol,
                    name=request.name,
                    asset_type=request.asset_type,
                    currency=request.currency,
                    sector=request.sector,
                    core_quantity=request.core_quantity,
                    tactical_quantity=request.tactical_quantity,
                    average_cost=request.average_cost,
                    core_average_cost=request.core_average_cost,
                    tactical_average_cost=request.tactical_average_cost,
                    core_reason=request.core_reason,
                    tactical_reason=request.tactical_reason,
                    operation=request.operation,
                ),
            )
        except ApplicationError as exc:
            if exc.code is ApplicationErrorCode.PORTFOLIO_NOT_FOUND:
                raise HTTPException(status_code=404, detail=exc.code.value) from exc
            raise HTTPException(status_code=422, detail=exc.code.value) from exc
        return _portfolio_response(view)

    @application.get(
        "/api/v1/watchlist",
        response_model=list[WatchlistItemResponse],
        tags=["watchlist"],
    )
    async def list_watchlist() -> list[WatchlistItemResponse]:
        items = await selected_watchlist_service.list_items()
        return [WatchlistItemResponse.model_validate(item, from_attributes=True) for item in items]

    @application.post(
        "/api/v1/watchlist",
        response_model=WatchlistItemResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["watchlist"],
    )
    async def add_watchlist_item(request: InstrumentIdentityRequest) -> WatchlistItemResponse:
        from investment_os.application.errors import ApplicationError
        from investment_os.domain.instrument import InstrumentIdentity

        try:
            identity = InstrumentIdentity(
                market=request.market,
                symbol=request.symbol,
                name=request.name,
                asset_type=request.asset_type,
                currency=request.currency,
                sector=request.sector,
            )
            item = await selected_watchlist_service.add_instrument(identity)
        except ApplicationError as exc:
            raise HTTPException(status_code=422, detail=exc.code.value) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail="watchlist_write_invalid") from exc
        return WatchlistItemResponse.model_validate(item, from_attributes=True)

    @application.delete(
        "/api/v1/watchlist/{market}/{symbol}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["watchlist"],
    )
    async def remove_watchlist_item(market: str, symbol: str) -> Response:
        removed = await selected_watchlist_service.remove_instrument(market=market, symbol=symbol)
        if not removed:
            raise HTTPException(status_code=404, detail="watchlist_item_not_found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    def _csv_row_response(row: CsvRowResult) -> CsvRowResultResponse:
        payload: dict[str, object] = {
            "line_number": row.line_number,
            "status": row.status,
            "reason": row.reason,
            "existing_core_quantity": row.existing_core_quantity,
            "existing_tactical_quantity": row.existing_tactical_quantity,
            "existing_average_cost": row.existing_average_cost,
        }
        if row.normalized is not None:
            payload.update(
                {
                    "market": row.normalized.market,
                    "symbol": row.normalized.symbol,
                    "name": row.normalized.name,
                    "core_quantity": str(row.normalized.core_quantity),
                    "tactical_quantity": str(row.normalized.tactical_quantity),
                    "average_cost": str(row.normalized.average_cost),
                }
            )
        return CsvRowResultResponse.model_validate(payload)

    def _csv_preview_response(preview: CsvImportPreview) -> CsvImportPreviewResponse:
        return CsvImportPreviewResponse(
            total_rows=preview.total_rows,
            can_commit=preview.can_commit,
            requires_conflict_policy=preview.requires_conflict_policy,
            content_hash=preview.content_hash,
            valid=[_csv_row_response(row) for row in preview.valid],
            invalid=[_csv_row_response(row) for row in preview.invalid],
            duplicates=[_csv_row_response(row) for row in preview.duplicates],
            conflicts=[_csv_row_response(row) for row in preview.conflicts],
        )

    def _app_error_to_http(exc: Exception) -> HTTPException:
        from investment_os.application.errors import ApplicationError

        if isinstance(exc, ApplicationError):
            status_code = (
                404
                if exc.code.value.endswith("NOT_FOUND")
                else 409
                if "CONFLICT" in exc.code.value
                else 422
            )
            return HTTPException(
                status_code=status_code,
                detail={"code": exc.code.value, "message": exc.message, "details": exc.details},
            )
        return HTTPException(
            status_code=422, detail={"code": "INVALID_REQUEST", "message": str(exc)}
        )

    @application.post(
        "/api/v1/portfolios/{portfolio_id}/csv/preview",
        response_model=CsvImportPreviewResponse,
        tags=["portfolio"],
    )
    async def preview_portfolio_csv(
        portfolio_id: UUID, request: CsvImportRequest
    ) -> CsvImportPreviewResponse:
        from investment_os.application.errors import ApplicationError

        try:
            await selected_portfolio_book_service.get_portfolio(portfolio_id)
            preview = await selected_portfolio_csv_service.preview(portfolio_id, request.csv_text)
        except ApplicationError as exc:
            raise _app_error_to_http(exc) from exc
        return _csv_preview_response(preview)

    @application.post(
        "/api/v1/portfolios/{portfolio_id}/csv/confirm",
        response_model=CsvImportCommitResponse,
        tags=["portfolio"],
    )
    async def confirm_portfolio_csv(
        portfolio_id: UUID, request: CsvImportRequest
    ) -> CsvImportCommitResponse:
        from investment_os.application.errors import ApplicationError

        try:
            result = await selected_portfolio_csv_service.confirm(
                portfolio_id=portfolio_id,
                raw_text=request.csv_text,
                conflict_policy=request.conflict_policy,
                expected_preview_hash=request.expected_preview_hash,
            )
        except ApplicationError as exc:
            raise _app_error_to_http(exc) from exc
        return CsvImportCommitResponse(
            imported_count=result.imported_count,
            skipped_count=result.skipped_count,
            conflict_policy=result.conflict_policy,
            audit_id=result.audit_id,
            applied=[
                {
                    "line_number": row.line_number,
                    "market": row.market,
                    "symbol": row.symbol,
                    "action": row.action,
                    "before": row.before,
                    "after": row.after,
                }
                for row in result.applied
            ],
            portfolio=_portfolio_response(result.portfolio),
        )

    @application.get(
        "/api/v1/portfolios/{portfolio_id}/import-audits",
        response_model=list[dict[str, object]],
        tags=["portfolio"],
    )
    async def list_import_audits(
        portfolio_id: UUID, limit: int = Query(default=20, ge=1, le=50)
    ) -> list[dict[str, object]]:
        from investment_os.application.errors import ApplicationError, ApplicationErrorCode

        try:
            return await selected_portfolio_book_service.list_import_audits(
                portfolio_id=portfolio_id, limit=limit
            )
        except ApplicationError as exc:
            if exc.code is ApplicationErrorCode.PORTFOLIO_NOT_FOUND:
                raise HTTPException(status_code=404, detail=exc.code.value) from exc
            raise HTTPException(status_code=422, detail=exc.code.value) from exc

    @application.get(
        "/api/v1/policy/review",
        response_model=PolicyReviewResponse,
        tags=["policy"],
    )
    async def policy_review() -> PolicyReviewResponse:
        """Read-only policy surface. Uses stored policy when present; never invents limits."""

        from investment_os.infrastructure.persistence.models import (
            InvestmentPolicyRecord,
            InvestmentPolicyVersionRecord,
        )

        if reader_engine is None and session_factory is None:
            return PolicyReviewResponse(
                active_policy_version="none",
                policy_status="TEST_DEFAULT",
                is_test_default=True,
                limits=[],
                warning="TEST_DEFAULT 不是投资建议. 真实限额须所有者治理批准后才可变更.",
            )
        assert session_factory is not None
        async with session_factory() as session:
            statement = (
                select(InvestmentPolicyRecord)
                .order_by(InvestmentPolicyRecord.created_at.desc())
                .limit(1)
            )
            policy = (await session.scalars(statement)).first()
            if policy is None or policy.current_version_id is None:
                return PolicyReviewResponse(
                    active_policy_version="none",
                    policy_status="TEST_DEFAULT",
                    is_test_default=True,
                    limits=[],
                    warning="TEST_DEFAULT 不是投资建议. 尚未激活经批准的投资政策.",
                )
            version = await session.get(InvestmentPolicyVersionRecord, policy.current_version_id)
            limits: list[dict[str, str]] = []
            if version is not None and isinstance(version.config_json, dict):
                for key, value in version.config_json.items():
                    limits.append({"key": str(key), "value": str(value)})
            policy_label = f"{policy.name}@{version.version if version else policy.version}"
            return PolicyReviewResponse(
                active_policy_version=policy_label,
                policy_status=policy.status,
                is_test_default=str(policy.name).upper().startswith("TEST"),
                limits=limits,
                warning=(
                    "只读展示已存政策配置; 修改真实限额需所有者治理批准."
                    if policy.status == "ACTIVE"
                    else "当前政策未处于 ACTIVE; 请在治理流程中确认."
                ),
            )

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

        @application.get("/portfolio", include_in_schema=False)
        async def portfolio_ui() -> FileResponse:
            return FileResponse(frontend_dist / "index.html")

        @application.get("/watchlist", include_in_schema=False)
        async def watchlist_ui() -> FileResponse:
            return FileResponse(frontend_dist / "index.html")

        @application.get("/journal", include_in_schema=False)
        async def journal_ui() -> FileResponse:
            return FileResponse(frontend_dist / "index.html")

        @application.get("/opportunities", include_in_schema=False)
        async def opportunities_ui() -> FileResponse:
            return FileResponse(frontend_dist / "index.html")

    return application
