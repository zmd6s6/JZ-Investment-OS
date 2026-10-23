const fields = {
  state: "逻辑状态", long_term_summary: "长期投资逻辑摘要", pillars: "逻辑支柱及支持证据",
  catalysts: "催化剂及支持证据", risks: "风险主张及支持证据",
  invalidation_conditions: "失效条件", monitoring_conditions: "持续观察事项", change_reason: "修订原因",
} as const;
type Fields = Record<keyof typeof fields, unknown>;
const names: Record<string, string> = { UNKNOWN: "未知", VALID: "有效／成立", STRENGTHENING: "增强", WEAKENING: "减弱", BROKEN: "已失效", AT_RISK: "受挑战", INVALID: "不成立", HUMAN_CORRECTION: "人工整理／修正", NEW_EVIDENCE: "新增证据", SCHEDULED_REVIEW: "定期复核", EVENT: "事件变化" };
function display(value: unknown): string {
  if (value === undefined) return "尚无已保存内容";
  if (typeof value === "string") return names[value] ?? (value || "（空）");
  return JSON.stringify(value, null, 2);
}

export function ThesisDraftChanges({ before, after }: { before: Fields | null; after: Fields }) {
  const changed = (Object.keys(fields) as (keyof Fields)[]).filter(key => JSON.stringify(before?.[key]) !== JSON.stringify(after[key]));
  return <details className="evidence-card"><summary>保存前核对修改（{changed.length} 项）</summary>
    <p className="hint-text">仅对比当前编辑草稿与载入的基准，不写入、不调用模型；不是服务端语义判断或投资批准。保存时仍由服务端检查最新版本与证据。未保存内容离页会丢失。</p>
    {!changed.length ? <p>当前草稿与载入版本一致。最终是否创建新版本由服务端判断。</p> : changed.map(key => <section key={key}>
      <h4>{fields[key]}</h4><p>修改前</p><pre className="evidence-excerpt">{display(before?.[key])}</pre>
      <p>当前草稿（尚未保存）</p><pre className="evidence-excerpt">{display(after[key])}</pre>
    </section>)}
  </details>;
}
