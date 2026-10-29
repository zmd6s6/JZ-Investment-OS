"""Explicit source-declared CSV intake and whole-snapshot bounded screening."""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from investment_os.application.market_data import MarketDataError
from investment_os.application.opportunities import OpportunityError
from investment_os.application.universe_snapshots import (
    UniverseBoundRun,
    UniverseConfirm,
    UniverseError,
    UniverseImport,
    UniverseOrigin,
    UniversePreview,
    UniverseRun,
    UniverseSnapshot,
    UniverseSnapshotService,
    UniverseSummary,
)

MESSAGES = {
    "UNIVERSE_CSV_HEADER": "CSV首行必须严格为market,symbol。没有导入。",
    "UNIVERSE_CSV_ROW": "CSV行格式、列数或标的代码不规范。没有丢弃错误行或导入部分集合。",
    "UNIVERSE_MARKET_MISMATCH": "成员市场与来源声明不一致, 整批拒绝。",
    "UNIVERSE_DUPLICATE": "CSV存在重复成员, 整批拒绝, 不静默去重。",
    "UNIVERSE_COUNT_MISMATCH": "实际成员数与声明总数不同, 整批拒绝。",
    "UNIVERSE_UNKNOWN_MEMBER": "存在本地目录不能精确解析的标的, 整批拒绝。请先登记标的后重新预览。",
    "UNIVERSE_CURRENCY_UNSUPPORTED": "此标的不是人民币, 缺FX, 当前不能导入该集合。",
    "UNIVERSE_FUTURE_SOURCE": "来源业务时间不能在未来。没有导入。",
    "UNIVERSE_PREVIEW_CONFLICT": "来源、内容或目录身份已变化, 请重新预览和明确确认。",
    "UNIVERSE_SCAN_BOUND_EXCEEDED": "快照超过200项, 当前不支持完整扫描。没有截断、抽样或拼接候选。",
    "UNIVERSE_NOT_YET_AVAILABLE": "筛选时点早于来源或本次入库时间, 禁止前视读取。",
    "UNIVERSE_NOT_FOUND": "该来源快照不存在, 请刷新历史。",
    "UNIVERSE_SNAPSHOT_INVALID": "来源快照无法核对, 已停止读取和筛选。请保留历史检查部署。",
    "UNIVERSE_SNAPSHOT_CONFLICT": "快照摘要与本次明确选择不一致, 请重新读取。",
    "UNIVERSE_ORIGIN_INVALID": "筛选与来源关联无法核对, 不展示已确认的来源。",
    "REQUEST_CONTENT_CONFLICT": "请求编号已用于其他内容或已有手选运行, 请核对后明确创建新请求。",
    "FUTURE_AS_OF_NOT_ALLOWED": "筛选时点不能在未来。",
}


def universe_router(service: UniverseSnapshotService | None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/opportunities/universes", tags=["universe-snapshots"])

    def ready() -> UniverseSnapshotService:
        if service is None:
            raise HTTPException(
                503,
                detail={
                    "code": "UNIVERSE_UNAVAILABLE",
                    "message": "来源集合导入未装配, 没有导入或筛选。",
                },
            )
        return service

    def failure(exc: UniverseError | OpportunityError | MarketDataError) -> HTTPException:
        return HTTPException(
            409 if "CONFLICT" in exc.code else 404 if exc.code == "UNIVERSE_NOT_FOUND" else 422,
            detail={
                "code": exc.code,
                "message": MESSAGES.get(
                    exc.code, "输入或本地资料无法核对, 未确认操作。请核对范围、日期和来源后重试。"
                ),
                "row": exc.row if isinstance(exc, UniverseError) else None,
            },
        )

    @router.post("/preview", response_model=UniversePreview)
    async def preview(command: UniverseImport) -> UniversePreview:
        try:
            return await ready().preview(command)
        except (UniverseError, OpportunityError, MarketDataError) as exc:
            raise failure(exc) from None

    @router.post("/imports", response_model=UniverseSnapshot)
    async def confirm(command: UniverseConfirm) -> UniverseSnapshot:
        try:
            return await ready().confirm(command)
        except (UniverseError, OpportunityError, MarketDataError) as exc:
            raise failure(exc) from None

    @router.get("", response_model=tuple[UniverseSummary, ...])
    async def history() -> tuple[UniverseSummary, ...]:
        try:
            return await ready().list()
        except UniverseError as exc:
            raise failure(exc) from None

    @router.get("/origins/{run_id}", response_model=UniverseOrigin | None)
    async def origin(run_id: UUID) -> UniverseOrigin | None:
        try:
            return await ready().origin(run_id)
        except UniverseError as exc:
            raise failure(exc) from None

    @router.get("/{snapshot_id}", response_model=UniverseSnapshot)
    async def detail(snapshot_id: UUID) -> UniverseSnapshot:
        try:
            return await ready().get(snapshot_id)
        except UniverseError as exc:
            raise failure(exc) from None

    @router.post("/{snapshot_id}/runs", response_model=UniverseBoundRun)
    async def run(snapshot_id: UUID, command: UniverseRun) -> UniverseBoundRun:
        try:
            return await ready().run(snapshot_id, command)
        except (UniverseError, OpportunityError, MarketDataError) as exc:
            raise failure(exc) from None

    return router
