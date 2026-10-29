const record = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const list = (value: unknown): unknown[] => Array.isArray(value) ? value : [];
const text = (value: unknown) => typeof value === "string" || typeof value === "number" ? String(value) : "未提供";
const decimal = (value: unknown) => text(typeof value === "object" ? record(value).value : value);
const roles: Record<string, string> = { MACRO: "宏观", INDUSTRY: "行业", FUNDAMENTAL: "基本面", MARKET_QUANT: "市场与量化", EVENT: "事件", DEVILS_ADVOCATE: "反方", PORTFOLIO: "组合经理", RISK: "风险", CIO: "投资负责人" };

export function DecisionCenterTrace({ lineage }: { lineage: Record<string, unknown> }) {
  const thesis = record(lineage.thesis), output = record(lineage.sizing_output);
  const opinions = list(lineage.opinions);
  return <section aria-label="决策依据追溯">
    <h4>固定论点与确定性结果</h4>
    {Object.keys(thesis).length ? <><p>{text(thesis.state)} · {text(thesis.summary)}</p><ul>{list(thesis.monitoring).map((condition, i) => <li key={i}>{text(condition)}</li>)}</ul></> : <p>没有固定论点内容，不能推断逻辑成立。</p>}
    <p>目标权重 {decimal(output.target_weight)} · 变化权重 {decimal(output.delta_weight)}<br />目标数量 {decimal(output.target_quantity)} · 变化数量 {decimal(output.delta_quantity)}<br />舍入前变化数量 {decimal(output.pre_rounding_delta_quantity)}<br />公式 {text(output.formula_version)} · 输入hash {text(output.input_hash)}</p>
    {list(output.reason_codes).length ? <ul>{list(output.reason_codes).map((code, i) => <li key={i}>确定性条件 {text(code)}</li>)}</ul> : <p>无额外公式原因记录，不据此推断风险通过。</p>}
    <h4>委员会角色与反方意见</h4>
    {!opinions.length ? <p>该历史决策没有已保存的角色观点正文；不补造意见，也不把空记录视为委员会成功证据。</p> : opinions.map((item, index) => {
      const opinion = record(item);
      return <details key={index}><summary>{roles[text(opinion.role)] ?? text(opinion.role)} · 第{text(opinion.round)}轮 · {text(opinion.stance)}</summary><p>模型 {text(opinion.model)} · Prompt {text(opinion.prompt_version)} · 置信度 {text(opinion.confidence)}<br />Opinion {text(opinion.opinion_id)}</p>
        {list(opinion.observations).map((item, i) => { const fact = record(item); return <p key={i}>{text(fact.claim)}<br /><small>事实引用 {list(fact.evidence_ids).map(text).join("、")}</small></p>; })}
        <ul>{[...list(opinion.assumptions), ...list(opinion.unknowns)].map((item, i) => <li key={i}>假设或未知：{text(item)}</li>)}</ul>
      </details>;
    })}
  </section>;
}
