/** Human-readable labels for machine failure codes shown in the analysis UI. */

export function tokenPriceLabel(value: unknown): string {
  if (typeof value !== "string" || !value) return "未配置";
  // Presentation only: strip database padding without Number/float conversion.
  return /^-?\d+\.\d+$/.test(value) ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
}

const FAILURE_LABELS: Record<string, string> = {
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
