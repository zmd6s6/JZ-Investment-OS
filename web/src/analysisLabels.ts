/** Human-readable labels for machine failure codes shown in the analysis UI. */

export function tokenPriceLabel(value: unknown): string {
  if (typeof value !== "string" || !value) return "未配置";
  // Presentation only: strip database padding without Number/float conversion.
  return /^-?\d+\.\d+$/.test(value) ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
}

const FAILURE_LABELS: Record<string, string> = {
  SIZING_CONTEXT_INCOMPLETE: "仓位输入尚不完整，未生成建议数量",
  PRICE_FRESHNESS_UNVERIFIED: "报价的交易级新鲜度与真实可用时间尚未验证",
  VOLATILITY_INPUT_MISSING: "缺少可追溯的波动率特征，不使用固定 20%",
  LIQUIDITY_CAPACITY_MISSING: "缺少流动性容量，不按 100% 填充",
  RISK_BUDGET_CAPACITY_MISSING: "缺少确定性风险预算容量，不按 100% 填充",
  LOT_SIZE_MISSING: "缺少已核实的交易单位，不默认一股",
  PENDING_EXPOSURE_UNAVAILABLE: "待执行暴露尚未接入权威读取，不推定为零",
  SECTOR_CLASSIFICATION_INCOMPLETE: "持仓行业分类或市值不完整，不推定零暴露",
  TARGET_SECTOR_MISSING: "分析标的缺少明确行业分类",
  VALUATION_INCOMPLETE: "净值或目标报价不完整，不能计算建议数量",
  VALUATION_INPUT_INVALID: "冻结持仓或现金输入校验失败",
  INVALID_REFERENCE_QUOTES: "报价身份、币种、价格或时间校验失败",
  ANALYSIS_STRATEGY_SNAPSHOT_MISSING: "旧任务未固定独立测试策略，未调用模型，请核对后明确新建运行",
  ANALYSIS_STRATEGY_CHANGED: "固定测试策略、代码或主表校验失败，未自动换版本或调用模型",
  ANALYSIS_RECORDING_FAILED: "研究主表保存失败，未发布成功报告，不自动重放模型，请核对费用",
  THESIS_UNKNOWN: "投资逻辑缺失或支持资料不新鲜，本次按未知处理",
  THESIS_BROKEN_REVIEW_REQUIRED: "已失效的持仓逻辑要求复核，减仓候选不是交易授权",
  ANALYSIS_THESIS_INVALID: "固定投资逻辑的版本、内容或支持资料校验失败",
  ANALYSIS_THESIS_SNAPSHOT_MISSING: "旧任务未固定投资逻辑，未自动调用当前模型",
  ANALYSIS_THESIS_EVIDENCE_UNAVAILABLE: "排队期间投资逻辑支持资料已过期，未调用模型",
  SIZING_STRATEGY_NOT_APPROVED: "仓位公式仍为工程测试版，独立策略未批准，不允许新增暴露",
  ANALYSIS_GOVERNANCE_SNAPSHOT_MISSING: "旧任务未固定政策与运行规则，未自动调用模型",
  ANALYSIS_GOVERNANCE_CHANGED: "固定政策或运行规则校验失败，未自动调用新版本",
  ANALYSIS_MARKET_AUDIT_UNAVAILABLE: "行情记录保存不可用，已停止继续调用，请核对费用",
  ANALYSIS_MARKET_CONFIGURATION_CHANGED: "固定行情档案已修改或停用，未自动换源",
  ANALYSIS_MODEL_CONFIGURATION_CHANGED: "固定模型配置已改变或停用，未自动换用模型",
  ANALYSIS_MODEL_CONFIGURATION_MISSING: "旧任务未固定模型配置，未自动调用当前模型",
  // run-level failure_code
  INSUFFICIENT_EVIDENCE: "缺少可用证据",
  GATEWAY_FAILURE: "模型服务调用失败",
  ANALYSIS_FAILED: "分析失败",
  AGENT_OPINION_INVALID: "模型输出未通过结构校验",
  AGENT_OPINION_EVIDENCE_UNAVAILABLE: "模型引用了不可用的证据",
  AGENT_ROLE_UNREGISTERED: "分析角色未注册",
  AGENT_RUNTIME_REQUEST_INVALID: "分析请求参数无效",
  PORTFOLIO_NOT_FOUND: "组合不存在",
  ANALYSIS_INTERRUPTED: "工作进程中断，未自动重放付费调用",
  ANALYSIS_CANCELLED: "分析已取消",
  ANALYSIS_EXECUTION_FAILED: "分析执行异常，请核对配置和费用",
  ANALYSIS_EVIDENCE_UNAVAILABLE: "排队时资料已失效，未调用模型",
  // payload.failures (fail-closed limitations)
  MISSING_REFERENCE_QUOTES: "缺少行情报价",
  RISK_AGENT_UNAVAILABLE: "风险评估未完成",
  INSUFFICIENT_VALUATION_FOR_EXPOSURE: "估值数据不足，不允许加仓",
  RISK_VETO_BLOCKED_BUY_ADD: "风险否决，买入/加仓已阻断",
  FX_SOURCE_MISSING_MULTI_CURRENCY: "跨币种缺少汇率数据",
  NAV_NON_POSITIVE: "组合净值非正",
  SIZING_INPUT_INVALID: "仓位计算输入无效",
  // per-opinion failure
  INVALID_OUTPUT: "模型输出格式不合规，自动修复后仍失败",
};

/**
 * Render a failure code as "中文说明（CODE）"; unknown codes pass through so
 * information is never hidden.
 */
export function explainFailure(code: string): string {
  const label = FAILURE_LABELS[code];
  return label ? `${label}（${code}）` : code;
}

const STATUS_LABELS: Record<string, string> = {
  SUCCEEDED: "成功",
  FAILED: "失败",
  RUNNING: "运行中",
  QUEUED: "已排队",
  CANCELLED: "已取消",
};

export function runStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

const ACTION_LABELS: Record<string, string> = {
  WATCH: "观望",
  BUY: "买入",
  ADD: "加仓",
  HOLD: "持有",
  REDUCE: "减仓",
  EXIT: "退出",
  AVOID: "回避",
};

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action;
}

const GATE_LABELS: Record<string, string> = {
  PASS: "通过",
  FAIL: "未通过",
  UNKNOWN: "未知",
  VETO: "否决",
};

export function gateLabel(gate: string): string {
  return GATE_LABELS[gate] ?? gate;
}

const STANCE_LABELS: Record<string, string> = {
  STRONGLY_NEGATIVE: "强烈负面",
  NEGATIVE: "负面",
  NEUTRAL: "中性",
  POSITIVE: "正面",
  STRONGLY_POSITIVE: "强烈正面",
  INSUFFICIENT_DATA: "数据不足",
};

export function stanceLabel(stance: string): string {
  return STANCE_LABELS[stance] ?? stance;
}
