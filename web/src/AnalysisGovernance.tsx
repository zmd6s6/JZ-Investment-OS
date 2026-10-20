export const POLICY_LIMIT_NAMES: Record<string, string> = {
  single_instrument_max_pct: "单标的上限（%）", sector_max_pct: "行业上限（%）",
  gross_exposure_max_pct: "总暴露上限（%）", minimum_cash_pct: "最低现金（%）",
  core_ratio_target: "核心仓目标比例", tactical_ratio_target: "战术仓目标比例",
};
const roleNames: Record<string, string> = { MACRO: "宏观", INDUSTRY: "行业", FUNDAMENTAL: "基本面", MARKET_QUANT: "市场与量化", EVENT: "事件", DEVILS_ADVOCATE: "反方审查", PORTFOLIO: "组合经理", RISK: "风险经理" };

export function AnalysisGovernance({ value }: { value: unknown }) {
  if (!value || typeof value !== "object") return <p className="hint-text">此旧报告未记录完整政策与运行规则快照，不用当前版本追补。</p>;
  const plan = value as { policy?: { mode?: string; policy_version_id?: string; version?: number; content_hash?: string; config?: { metadata?: { name?: string }; position?: Record<string, unknown> } }; formula?: { version?: string; status?: string }; prompts?: { role: string; version: string; content_hash: string }[] };
  const policy = plan.policy;
  return <details><summary>政策与运行规则版本 · 只读快照</summary>
    <p>政策：{policy?.mode === "TEST_DEFAULT" ? "TEST_DEFAULT（工程测试值）" : `${policy?.config?.metadata?.name ?? "未记录"}@${policy?.version ?? "未知"}`}</p>
    <p className="hint-text" style={{ overflowWrap: "anywhere" }}>政策版本 ID：{policy?.policy_version_id ?? "无真实批准版本"} · 内容摘要 {policy?.content_hash ?? "未记录"}</p>
    <p className="context-note">以下是提交时固定的配置，不查询当前政策补写。测试值不是真实投资限额；当前公式仍是 TEST_DEFAULT，不据此允许买入或加仓。</p>
    <ul className="tip-list">{Object.entries(policy?.config?.position ?? {}).map(([name, number]) => <li key={name}>{POLICY_LIMIT_NAMES[name] ?? name}：{String(number)}</li>)}</ul>
    <p>仓位公式：{plan.formula?.version ?? "未记录"} · {plan.formula?.status ?? "未知"}</p>
    <p className="hint-text">独立策略版本尚未接入，不伪造已批准策略。固定参数不等于完整估值、真实特征或交易授权。</p>
    <h4>本次固定的 Prompt 内容摘要</h4>
    <ul className="tip-list">{plan.prompts?.map((prompt) => <li key={prompt.role}><strong>{roleNames[prompt.role] ?? prompt.role} · {prompt.version}</strong><p className="hint-text" style={{ overflowWrap: "anywhere" }}>{prompt.content_hash}</p></li>)}</ul>
    <details><summary>完整政策、公式参数与工具白名单</summary><pre className="hint-text">{JSON.stringify(value, null, 2)}</pre></details>
  </details>;
}
