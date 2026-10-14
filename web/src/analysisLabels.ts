/** Human-readable labels for machine failure codes shown in the analysis UI. */

const FAILURE_LABELS: Record<string, string> = {
  // run-level failure_code
  INSUFFICIENT_EVIDENCE: "缺少可用证据",
  GATEWAY_FAILURE: "模型服务调用失败",
  ANALYSIS_FAILED: "分析失败",
  AGENT_OPINION_INVALID: "模型输出未通过结构校验",
  AGENT_OPINION_EVIDENCE_UNAVAILABLE: "模型引用了不可用的证据",
  AGENT_ROLE_UNREGISTERED: "分析角色未注册",
  AGENT_RUNTIME_REQUEST_INVALID: "分析请求参数无效",
  PORTFOLIO_NOT_FOUND: "组合不存在",
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
