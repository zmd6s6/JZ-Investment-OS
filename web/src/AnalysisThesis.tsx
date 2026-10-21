const states: Record<string, string> = { UNKNOWN: "未知", VALID: "有效", STRENGTHENING: "增强", WEAKENING: "减弱", BROKEN: "已失效" };
type Version = { id: string; thesis_id: string; version: number; parent_version_id?: string; content_hash: string; created_at: string; content: { state: string; long_term_summary: string; pillars: { key: string; status: string; claim: { description: string; evidence_ids: string[] } }[]; monitoring_conditions: string[] } };
type Input = { effective_state: string; as_of: string; version: Version | null; evidence: { evidence_id: string; freshness: string; content_hash: string }[] };

export function AnalysisThesis({ value }: { value: unknown }) {
  if (!value || typeof value !== "object") return <p className="hint-text">此旧报告未固定投资逻辑版本，不用当前记录补写。</p>;
  const input = value as Input;
  if (!input.version) return <section className="context-note" aria-label="投资逻辑快照"><strong>投资逻辑：未知</strong><p>本次分析时点没有可用的已保存版本，不默认为有效，也未自动创建。角色观点不等于已建立的长期投资逻辑。</p></section>;
  const version = input.version;
  return <details><summary>投资逻辑 · 固定版本 {version.version} · {states[input.effective_state] ?? "未知"}</summary>
    <p>记录状态：{states[version.content.state] ?? version.content.state} · 本次规则使用：{states[input.effective_state] ?? "未知"}</p>
    <p className="context-note">这是提交时保存的历史版本，不是本轮模型新建的结论。支持资料陈旧或到期时不据此增加暴露；已失效逻辑仍要求复核。有持仓时生成减仓复核候选，不代表获批或已成交。</p>
    <p>{version.content.long_term_summary}</p>
    <p className="hint-text" style={{ overflowWrap: "anywhere" }}>版本 ID：{version.id} · 内容摘要：{version.content_hash}<br />前版 ID：{version.parent_version_id ?? "首版"} · 保存：{version.created_at} · 分析时点：{input.as_of}</p>
    <h4>长期逻辑支柱（历史主张）</h4>
    <ul className="tip-list">{version.content.pillars.map((pillar) => <li key={pillar.key}>{pillar.claim.description}<p className="hint-text">支柱 {pillar.key} · {pillar.status} · 引用 {pillar.claim.evidence_ids.join("、")}</p></li>)}</ul>
    <h4>持续观察条件</h4><ul>{version.content.monitoring_conditions.map((condition, index) => <li key={index}>{condition}</li>)}</ul>
    <p className="hint-text">旧逻辑的引用不自动加入本次所选证据；新事实仍须引用本次有效资料。</p>
    <details><summary>完整版本、失效条件与支持资料状态</summary><pre className="hint-text">{JSON.stringify(input, null, 2)}</pre></details>
  </details>;
}
