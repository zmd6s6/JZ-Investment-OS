"""Read-only build delivery manifest; never records human acceptance or probes providers."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class CapabilityDelivery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    key: str
    label: str
    work_item: str
    engineering: Literal["IMPLEMENTED", "PARTIAL", "NOT_IMPLEMENTED"]
    integration: Literal["INTEGRATED", "BASELINE_ONLY", "NOT_IMPLEMENTED"]
    human_acceptance: Literal["PENDING"] = "PENDING"
    service: Literal["ASSEMBLED", "UNAVAILABLE", "NOT_APPLICABLE"]
    route: str | None
    detail: str
    steps: tuple[str, ...]
    failure: str


class AcceptanceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    release: Literal["MVP-BETA"] = "MVP-BETA"
    evidence_basis: Literal["BUILD_MANIFEST_AND_SERVICE_ASSEMBLY"] = (
        "BUILD_MANIFEST_AND_SERVICE_ASSEMBLY"
    )
    auto_trade: Literal[False] = False
    capabilities: tuple[CapabilityDelivery, ...]


def acceptance_snapshot(
    *,
    portfolio: bool,
    watchlist: bool,
    providers: bool,
    policy: bool,
    calendar: bool = False,
    market_data: bool = False,
) -> AcceptanceSnapshot:
    """Declare shipped paths separately from composition and owner confirmation.

    ASSEMBLED means the use case was wired, not that its database/provider is healthy.
    This manifest must change with delivery evidence, never from a browser checkbox.
    """
    wired = {
        "portfolio": portfolio,
        "watchlist": watchlist,
        "providers": providers,
        "policy": policy,
        "acceptance": True,
        "calendar": calendar,
        "market_data": market_data,
    }
    shipped = (
        (
            "market_data",
            "人工行情与币种边界",
            "MVP-201",
            "/market-data",
            "人工有来源报价可保存、追溯与刷新; 未经独立核实, 非自动行情或完整估值。",
            (
                "从设置进入人工行情, 选择已登记标的并填写出处、精确价格与业务时间。",
                "明确保存后读取指定来源, 核对Evidence、内容摘要和UTC时间; 刷新后再读取。",
                "检查缺失、过期、未来资料与跨币种失败提示; 不会借用旧价或默认汇率。",
            ),
            "输入错误保留内容; 结果未知可用同内容核对原请求。缺价或缺FX时不显示参考价格。",
        ),
        (
            "acceptance",
            "产品进度与验收",
            "MVP-000",
            "/acceptance",
            "只读查看当前构建的交付清单; 不替所有者接受产品。",
            (
                "打开本页, 区分工程、集成证据和人工验收。",
                "展开操作指引, 从入口进入产品, 再刷新核对。",
            ),
            "读取失败会明确提示, 可只读重试, 不显示缓存成功状态。",
        ),
        (
            "portfolio",
            "组合与持仓导入",
            "MVP-101",
            "/portfolio",
            "PR #17 已合并的手工持仓与CSV路径; 不包含行情估值。",
            (
                "创建组合, 填写币种和现金。",
                "手工保存持仓, 或预览CSV并修正错误后明确确认。",
                "刷新核对持仓、现金与导入记录。",
            ),
            "无效行必须提示错误且不能确认; 写入失败不应宣称已保存。",
        ),
        (
            "watchlist",
            "观察清单",
            "MVP-101",
            "/watchlist",
            "目录搜索与观察标的管理; 没有资料时必须显示未评估。",
            ("搜索标的并明确添加。", "刷新后检查清单, 再测试移除。"),
            "空结果与缺失逻辑 / 新鲜度应明确显示, 不生成虚构结论。",
        ),
        (
            "policy",
            "投资政策审阅",
            "MVP-101",
            "/#policy",
            "只读查看实际政策版本; TEST_DEFAULT不是已批准真实参数。",
            ("打开首页的投资政策区, 核对版本与测试政策提示。",),
            "没有政策或读取失败时显示缺失, 不自动选择真实限额。",
        ),
        (
            "providers",
            "模型与数据源设置",
            "PRODUCT-02 / PRODUCT-03 / PRODUCT-04",
            "/settings",
            "可配置档案; 配置成功不等于模型 / 数据连接成功或分析已就绪。",
            ("在设置中建立自己的已授权档案。", "只有明确点击测试连接才可能发生网络调用和费用。"),
            "无凭据、停用、连接或预算失败须明确显示, 不能静默换源。",
        ),
        (
            "calendar",
            "市场日历状态报告",
            "MVP-401",
            "/calendar",
            "已接通手工日历导入与Worker无付费状态报告; 不代表完整团队研究或真实定时费用授权。",
            (
                "核对来源后预览并导入明确交易时段, 新版本默认暂停。",
                "单独确认仅状态报告后启用, 查看实际任务与来源记录。",
            ),
            "格式错误整批拒绝; 没有日历或已暂停不调度, 无记录不冒充Worker健康。",
        ),
    )
    items = [
        CapabilityDelivery(
            key=key,
            label=label,
            work_item=item,
            engineering="IMPLEMENTED",
            integration="INTEGRATED",
            service="ASSEMBLED" if wired[key] else "UNAVAILABLE",
            route=route if wired[key] else None,
            detail=detail,
            steps=steps,
            failure=failure,
        )
        for key, label, item, route, detail, steps, failure in shipped
    ]
    pending = (
        (
            "analysis",
            "团队分析与追溯",
            "MVP-203 / MVP-204",
            "尚未在当前Release接通完整分析产品路径; 其他未合并分支不代表本构建能力。",
            False,
        ),
        (
            "decisions",
            "决策与人工批准",
            "MVP-301",
            "决策审阅、批准与手工执行页面尚未交付, 不提供订单入口。",
            False,
        ),
        (
            "runtime",
            "日常团队运行",
            "MVP-401",
            "只有底层调度基础; 产品日历、任务配置与运行页面尚未接通。",
            True,
        ),
        (
            "opportunities",
            "机会筛选",
            "MVP-402",
            "产品机会漏斗尚未交付, 不以合成演示冒充真实选股结果。",
            False,
        ),
    )
    items.extend(
        CapabilityDelivery(
            key=key,
            label=label,
            work_item=item,
            engineering="PARTIAL" if baseline else "NOT_IMPLEMENTED",
            integration="BASELINE_ONLY" if baseline else "NOT_IMPLEMENTED",
            service="NOT_APPLICABLE",
            route=None,
            detail=detail,
            steps=(),
            failure="当前没有可用产品入口; 请等待对应工作项接通, 不需要反复点击或补令牌。",
        )
        for key, label, item, detail, baseline in pending
    )
    return AcceptanceSnapshot(capabilities=tuple(items))
