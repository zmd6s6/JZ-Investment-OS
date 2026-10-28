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
    valuation: bool = False,
    opportunities: bool = False,
    analysis: bool = False,
    decisions: bool = False,
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
        "valuation": valuation,
    }
    shipped = (
        (
            "valuation",
            "参考估值与持仓对账",
            "MVP-202",
            "/valuation",
            "只读冻结现金和分仓并计算参考NAV/权重/暴露; 人工行情非交易级, 不是完整Sizing或分析。",
            (
                "先登记持仓和现金, 在人工行情记录同一明确来源的有效人民币报价。",
                "选择组合并输入准确来源名称, 读取估值, 核对分仓和来源Evidence。",
                "检查政策/历史波动率/流动性等缺口; 参考NAV不能授权投资行为。",
            ),
            "缺一笔有效价不给完整NAV或任何组合权重; 缺FX整组失败关闭; 无效输入保留并提示重试。",
        ),
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
    items.append(
        CapabilityDelivery(
            key="opportunities",
            label="有限范围机会漏斗",
            work_item="MVP-402",
            engineering="PARTIAL",
            integration="INTEGRATED",
            service="ASSEMBLED" if opportunities else "UNAVAILABLE",
            route="/opportunities" if opportunities else None,
            detail=(
                "本地手选范围和有来源人工年报事实的确定性漏斗已接通; "
                "全市场 / 深研 / 周定时尚未提供, 不是完整P8或交易建议。"
            ),
            steps=(
                "先登记标的并在人工行情保存报价。",
                "选择有限范围, 补录明确自然年 / EPS口径的事实, 输入本次查询条件后筛选。",
                "核对各层原因 / 缺项 / 有界候选及Evidence, 刷新读取不可变历史。",
            ),
            failure="缺价、缺项、过期、未来或无法核对口径时停止对应层; 深研未提供时不调用模型。",
        )
    )
    items.append(
        CapabilityDelivery(
            key="analysis",
            label="团队影子分析",
            work_item="MVP-203",
            engineering="PARTIAL",
            integration="INTEGRATED",
            service="ASSEMBLED" if analysis else "UNAVAILABLE",
            route="/analysis" if analysis else None,
            detail=(
                "显式选择输入与授权后排队, Worker保存真实阶段和两轮观点; "
                "当前风险与完整Sizing缺项, 只有不可执行的降级影子结论。"
                "可展开本次冻结资料与角色依据; 当前分析未产生完整Risk/Sizing或可审批InvestmentDecision。"
            ),
            steps=(
                "先配置模型凭据、单价与预算, 登记组合和研究标的。",
                "在分析页选择证据 / 可选研究源及每角色模型, 核对信息出站与可能费用后明确发起。",
                "观察阶段与失败, 刷新读历史; 取消只停止后续步骤, 重试新建运行且保留原历史。",
            ),
            failure=(
                "无有效证据不调用模型; 配置漂移、预算、无效输出或中断显式失败。"
                "缺政策 / 风险 / Sizing不伪造BUY、PASS或数量。"
            ),
        )
    )
    items.append(
        CapabilityDelivery(
            key="decisions",
            label="决策与人工批准",
            work_item="MVP-301",
            engineering="PARTIAL",
            integration="INTEGRATED",
            service="ASSEMBLED" if decisions else "UNAVAILABLE",
            route="/decisions" if decisions else None,
            detail=(
                "真实决策列表/审阅/具名人工动作/手工事实已接线; "
                "仅完整有效链可批准, 当前分析Shadow不可审批。"
            ),
            steps=(
                "从导航或设置进入决策中心, 审阅固定来源、风险、分仓与确定性数量。",
                "填写人工归属与理由, 明确确认后批准/拒绝或撤销未成交批准。",
                "外部已完成手工动作后填写数量/价格/费用/真实时间/引用/备注; 保存并刷新核对。",
            ),
            failure=(
                "缺Policy/Strategy/Risk/Sizing或输入漂移、到期、Veto等失败关闭; "
                "影子结论无审批入口, 不提交订单。"
            ),
        )
    )
    items.append(
        CapabilityDelivery(
            key="analysis_trace",
            label="分析依据与资料追溯",
            work_item="MVP-204",
            engineering="IMPLEMENTED",
            integration="INTEGRATED",
            service="ASSEMBLED" if analysis else "UNAVAILABLE",
            route="/analysis" if analysis else None,
            detail=(
                "只读展开同一运行的冻结Evidence、论点版本、两轮观点、来源时间与闸门原因; "
                "不重取资料、不调用模型, 不把未知风险或缺失仓位输入当作通过。"
            ),
            steps=(
                "进入分析页, 从组合的运行历史选择一次运行。",
                "在完整依据中核对模型提案与确定性裁决, 点击观点中的证据定位到保存的来源。",
                "查看四业务时间、到期/hash、冻结论点、分仓/政策版本及风险与Sizing缺项。",
                "刷新重读仍须保留当次历史; 尚未运行的阶段和不可核对引用明确显示未知。",
            ),
            failure=(
                "详情读取失败清空旧运行依据并显示错误; 尚无冻结输入或部分角色失败不补造结论。"
                "资料正文仅纯文本显示, 不自动打开来源或执行外部文字。"
            ),
        )
    )
    pending = (
        (
            "runtime",
            "日常团队运行",
            "MVP-401",
            "只有底层调度基础; 产品日历、任务配置与运行页面尚未接通。",
            True,
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
