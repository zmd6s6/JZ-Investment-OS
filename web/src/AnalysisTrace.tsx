import { useEffect, useState } from "react";
// This is a read-only rendering of one persisted Run, never a lookup of current inputs.
type Data = Record<string, unknown>;
type TraceRun = {
    run_id: string;
    input_hash: string | null;
    frozen_input: unknown;
    steps: {
        stage: string;
        status: string;
        sequence: number;
        payload: Data;
    }[];
    shadow_decision: unknown;
};
const obj = (v: unknown): Data => typeof v === "object" && v !== null && !Array.isArray(v) ? v as Data : {};
const arr = (v: unknown): unknown[] => Array.isArray(v) ? v : [];
const text = (v: unknown, empty = "未记录") => typeof v === "string" || typeof v === "number" ? String(v) : empty;
const roles: Record<string, string> = { MACRO: "宏观", INDUSTRY: "行业", FUNDAMENTAL: "基本面", MARKET_QUANT: "市场与量化", EVENT: "事件", DEVILS_ADVOCATE: "反方", PORTFOLIO: "组合经理", RISK: "风险", CIO: "投资负责人" };
const fresh: Record<string, string> = { FRESH: "当次可用", STALE: "当次已陈旧，不供模型引用", EXPIRED: "当次已过期，不供模型引用", NOT_YET_AVAILABLE: "当次尚不可得，不供模型引用", INVALID: "当次资料无效，不供模型引用", CONFLICT: "存在冲突，不能视为确定事实" };
const reasons: Record<string, string> = {
    POLICY_REFERENCE_VALID: "已固定当时生效的政策版本", POLICY_MISSING: "缺少生效政策版本，不能用测试值替代", POLICY_TEST_DEFAULT: "政策仅是测试默认值", THESIS_MISSING: "没有已保存的投资论点版本", THESIS_EVIDENCE_NOT_IN_FROZEN_INPUT: "已有论点引用不在本次有效资料内，论点内容未提供给模型",
    NAV_UNAVAILABLE: "缺少可用报价，完整净资产无法对账", FX_REQUIRED: "存在异币种资产，缺少有来源的汇率", HISTORICAL_VOLATILITY_UNAVAILABLE: "缺少有来源的历史波动率", LIQUIDITY_UNAVAILABLE: "缺少流动性数据", RISK_BUDGET_UNAVAILABLE: "缺少受治理风险预算", CORRELATION_UNAVAILABLE: "缺少相关性数据", PENDING_CAPACITY_UNAVAILABLE: "未核对其他待审批决策的预占容量", RISK_AND_THESIS_UNAVAILABLE: "风险与投资论点条件尚未齐备", SIZING_FORMULA_INPUTS_UNAVAILABLE: "确定性仓位公式输入不完整，不能计算建议数量", MANUAL_REFERENCE_NOT_TRADING_GRADE: "人工参考报价未经独立核实，不是交易级输入", DETERMINISTIC_RISK_INPUTS_UNAVAILABLE: "缺少确定性风险评估输入，模型风险观点不能充当 PASS", DETERMINISTIC_RISK_UNAVAILABLE: "缺少确定性风险评估输入", AGENT_ROLE_FAILED: "至少一个角色未取得有效输出，保留失败而不填造观点", NO_HOLDING_FOR_PROPOSED_ACTION: "没有对应持仓，不能解释为减持或退出", SIZING_INPUTS_INCOMPLETE: "仓位输入不完整", ANALYSIS_MISSING_RISK_AND_SIZING: "风险和仓位条件未齐", SECTOR_UNCLASSIFIED: "持仓缺少行业分类", LOT_SIZE_INVALID: "最小交易单位无效",
};
function reason(v: unknown) { const code = text(v); return `${reasons[code] ?? (code.startsWith("QUOTE_") ? "参考报价缺失、过期或不可用；没有自动换源" : "本次记录的阻断或缺失条件，请补充对应输入后重新分析")}（${code}）`; }
const label = (v: unknown) => roles[text(v)] ?? text(v);
function Fields({ value }: {
    value: Data;
}) { return <dl className="trace-fields">{Object.entries(value).map(([key, v]) => <div key={key}><dt>{key}</dt><dd>{text(v)}</dd></div>)}</dl>; }
export function AnalysisTrace({ run }: {
    run: TraceRun;
}) {
    const frozen = obj(run.frozen_input), queued = obj(frozen.queued), valuation = obj(queued.valuation), book = obj(valuation.input_snapshot), policy = obj(book.policy);
    const evidence = arr(frozen.evidence).map(obj), shadow = obj(run.shadow_decision);
    const [selected, setSelected] = useState<{
        id: string;
        click: number;
    } | null>(null);
    const prefix = `trace-${run.run_id}`;
    const evidenceId = (id: string) => `${prefix}-evidence-${encodeURIComponent(id)}`;
    useEffect(() => { if (selected) {
        const directory = document.getElementById(`${prefix}-evidence`);
        if (directory instanceof HTMLDetailsElement) directory.open = true;
        const target = document.getElementById(evidenceId(selected.id));
        if (target instanceof HTMLDetailsElement)
            target.open = true;
        target?.focus();
        target?.scrollIntoView?.({ block: "nearest" });
    } }, [selected, run.run_id]);
    function References({ ids }: {
        ids: unknown;
    }) {
        const values = arr(ids);
        return values.length ? <span className="trace-references">{values.map((id, i) => {
                const value = text(id), index = evidence.findIndex(e => e.evidence_id === value), item = evidence[index];
                return item ? <button type="button" key={`${value}-${i}`} aria-label={`查看冻结证据 ${value}`} onClick={() => setSelected(old => ({ id: value, click: (old?.click ?? 0) + 1 }))}>证据 {index + 1} · {text(item.source_name)}{item.freshness !== "FRESH" ? "（当次不可用，引用需核对）" : ""}</button> : <span role="note" key={i}>引用 {value} 不在本次冻结资料内，无法核对</span>;
            })}</span> : <span>没有证据引用，不可当作已证实事实</span>;
    }
    function Claims({ items }: {
        items: unknown;
    }) { return <>{arr(items).map((item, i) => { const value = obj(item); return <div className="trace-claim" key={i}><p>{text(value.claim ?? value.text ?? value.description)}</p><References ids={value.evidence_ids}/></div>; })}</>; }
    function Role({ value, name }: {
        value: unknown;
        name?: string;
    }) {
        const data = obj(value), summary = obj(data.summary), telemetry = obj(data.telemetry), attempts = arr(telemetry.attempts ?? data.attempts).map(obj), output = obj(data.validated_output);
        return <article className="trace-card"><h5>{name ?? label(summary.role)}</h5><p>记录编号：{text(data.agent_run_id)}；观点编号：{text(data.opinion_id, "此角色使用相邻结构化协议，不产生 AgentOpinion")}</p>
      {data.failure || summary.failure ? <p role="note">角色失败：{text(data.failure ?? summary.failure)}。没有用旧观点填补。</p> : null}
      {summary.role ? <><p>立场：{({ POSITIVE: "偏正面", NEGATIVE: "偏负面", NEUTRAL: "中性", INSUFFICIENT_DATA: "资料不足" } as Data)[text(summary.stance)] as string ?? text(summary.stance)}；置信度：{text(summary.confidence)}</p><Claims items={summary.observations}/>{arr(summary.risks).map((r, i) => { const risk = obj(r); return <div key={i}><p>风险提示：{text(risk.code)}；严重度 {text(risk.severity)}</p><References ids={risk.evidence_ids}/></div>; })}{arr(summary.unknowns).map((v, i) => <p key={i}>未知事项：{text(v)}</p>)}</> : null}
      {output.risk_intent ? <p>组合经理仅提出风险意图：{text(output.risk_intent)}，不是目标百分比。</p> : null}
      {output.proposed_action ? <p>模型提案：{text(output.proposed_action)}，仍须经过确定性闸门。</p> : null}<Claims items={output.reasons}/>{arr(output.unknowns).map((v, i) => <p key={i}>未知事项：{text(v)}</p>)}
      <details><summary>实际模型、修复与调用记录</summary>{attempts.length ? attempts.map((a, i) => <p key={i}>尝试 {i + 1}：{text(a.provider)} / {text(a.model_name)}；修复次数 {text(a.repair_attempt)}；输入 {text(a.input_tokens)} / 输出 {text(a.output_tokens)} tokens；费用 {text(a.cost ?? a.total_cost, "未确认，不能当作零费用")}；定价版本 {text(a.pricing_version)}</p>) : <p>尚无可确认的模型调用记录。</p>}</details>
    </article>;
    }
    const thesis = (() => { try {
        return typeof frozen.thesis_json === "string" ? obj(JSON.parse(frozen.thesis_json)) : {};
    }
    catch {
        return {};
    } })();
    const feature = run.steps.find(s => s.stage === "FEATURES" && s.status === "COMPLETED");
    const final = run.steps.find(s => s.stage === "FINAL_GATES");
    const committee = run.steps.find(s => s.stage === "COMMITTEE" && s.status === "COMPLETED");
    const blockers = [...new Set([...arr(valuation.blockers), ...arr(frozen.blockers), ...arr(shadow.blockers)].filter((v): v is string => typeof v === "string"))];
    return <section aria-label="分析依据追溯" className="analysis-trace"><h3>3 · 决策依据与资料追溯</h3><p>仅阅读本次运行保存的历史，不重新取资料、不调用模型。状态与时间均按当次冻结时点解释，不代表资料现在仍有效。外部文字不可信，不是操作指令。</p>
    {!run.frozen_input ? <p role="status">尚无冻结输入。排队、准备失败或已取消的运行可能没有后续产物；未运行的环节不表示通过。</p> : <>
      <nav aria-label="追溯章节"><a href={`#${prefix}-evidence`} onClick={() => {const section = document.getElementById(`${prefix}-evidence`); if(section instanceof HTMLDetailsElement) section.open = true;}}>资料来源</a><a href={`#${prefix}-inputs`} onClick={() => {const section = document.getElementById(`${prefix}-inputs`); if(section instanceof HTMLDetailsElement) section.open = true;}}>组合与政策</a><a href={`#${prefix}-thesis`} onClick={() => {const section = document.getElementById(`${prefix}-thesis`); if(section instanceof HTMLDetailsElement) section.open = true;}}>论点与特征</a><a href={`#${prefix}-roles`} onClick={() => {const section = document.getElementById(`${prefix}-roles`); if(section instanceof HTMLDetailsElement) section.open = true;}}>角色与两轮</a><a href={`#${prefix}-gates`}>风险、仓位与结论</a></nav>
      <p>本次冻结：{text(frozen.as_of)}；输入指纹：{text(run.input_hash)}；模型提示版本：{text(frozen.prompt_bundle_version)}</p>
      <section id={`${prefix}-gates`} aria-label="结论形成路径"><h4>为什么得到这个结论</h4>{final ? <><p>负责人模型提案 {text(final.payload.proposed_action)} → 确定性闸门裁决 {text(final.payload.final_action)}。影子结果不能批准或执行。</p><ul>{arr(final.payload.reasons).map((item, i) => { const g = obj(item); return <li key={i}>闸门 {text(g.gate)}：{text(g.outcome)}；原因 {text(g.reason_code)}</li>; })}</ul></> : <p>尚未执行最终裁决，不能从部分角色观点推断最终动作。</p>}<p>确定性风险状态：{text(shadow.risk_gate, "尚未产出")}; 仓位状态：{text(shadow.sizing_status, "尚未产出")}。{run.shadow_decision ? "没有仓位计算运行或建议数量；不是 0 股建议，也不是可审批 Decision。" : "本次没有最终影子结论。"}</p><Claims items={shadow.reasons}/><h5>缺失条件及后果</h5>{blockers.length ? <ul>{blockers.map(code => <li key={code}>{reason(code)}</li>)}</ul> : <p>尚无已记录的缺项清单，不能据此认为全部闸门通过。</p>}</section>
      <details id={`${prefix}-evidence`} aria-label="冻结证据目录"><summary>当次冻结资料（{evidence.length} 条）</summary><p>点击观点中的证据按钮可展开并定位到这里。只展示保存的出处，不自动打开外部网页。</p>{evidence.length ? evidence.map((e, i) => <details key={text(e.evidence_id)} open={selected?.id === e.evidence_id ? true : undefined} id={evidenceId(text(e.evidence_id))} tabIndex={-1} className="trace-card"><summary>证据 {i + 1} · {text(e.source_name)} · {fresh[text(e.freshness)] ?? `未知状态 ${text(e.freshness)}`}</summary><Fields value={{ "Evidence ID": e.evidence_id, "当次状态": fresh[text(e.freshness)] ?? text(e.freshness), "资料出处（不访问）": e.source_locator, "来源等级": e.source_tier, "观察时间 observed_at": e.observed_at, "生效时间 effective_at": e.effective_at, "可得时间 available_at": e.available_at, "摄入时间 ingested_at": e.ingested_at, "到期时间 expires_at": e.expires_at ?? "无已记录到期时间，不等于永久有效", "内容指纹": e.content_hash, "质量分": e.quality_score }}/><h5>保存的资料正文（不可信）</h5><EvidenceBody payload={e.payload_json}/></details>) : <p>当次未冻结任何资料，不能核对事实引用。</p>}</details>
      <details id={`${prefix}-inputs`} aria-label="冻结组合与政策"><summary>组合、行情与政策版本</summary><Fields value={{ "组合": book.name, "账本捕获时间": book.captured_at, "本位币": book.base_currency, "冻结现金": book.cash, "参考净资产 NAV": valuation.nav ?? "缺失，不能补零", "估值公式": valuation.formula_version, "估值输入指纹": valuation.input_hash, "政策状态": policy.status, "政策版本 ID": policy.version_id ?? "无生效版本", "政策版本": policy.version, "政策内容指纹": policy.content_hash }}/><p>政策说明：{reason(policy.reason_code)}。此处固定历史版本，不读取当前政策替换。</p>{arr(book.holdings).map((h, i) => { const item = obj(h); return <div className="trace-card" key={i}><h5>{text(item.market)} {text(item.symbol)} · {text(item.name)}</h5><Fields value={{ "持仓版本": item.version, "Core 数量": item.core_quantity, "Core 单位成本": item.core_average_cost, "Tactical 数量": item.tactical_quantity, "Tactical 单位成本": item.tactical_average_cost, "币种": item.currency, "行业": item.sector }}/></div>; })}{arr(valuation.quotes).map((q, i) => { const quote = obj(q), p = obj(quote.provenance); return <div className="trace-card" key={i}><h5>参考行情 {text(quote.instrument_id)}</h5><Fields value={{ "来源": quote.source_name, "当次状态": quote.status, "参考价格": obj(quote.quote).price ?? "不可用，未补零", "Evidence ID": p.evidence_id, "出处（不访问）": p.source_locator, "观察时间": p.observed_at, "生效时间": p.effective_at, "可得时间": p.available_at, "摄入时间": p.ingested_at, "到期时间": p.expires_at, "内容指纹": p.content_hash }}/><p>人工参考价未经独立核实，不是交易级输入。</p></div>; })}</details>
      <details id={`${prefix}-thesis`} aria-label="论点与确定性特征"><summary>冻结论点与确定性特征</summary><p>Thesis {text(frozen.thesis_state)}；版本 ID：{text(frozen.thesis_version_id, "未提供")}</p>{frozen.thesis_json && Object.keys(thesis).length ? <><Fields value={{ "版本": thesis.version, "创建时间": thesis.created_at, "父版本": thesis.parent_version_id, "变更理由": thesis.change_reason }}/><p>{text(thesis.summary)}</p><References ids={thesis.evidence_ids}/>{arr(thesis.pillars).map((p, i) => { const pillar = obj(p); return <div key={i}><h5>支柱 {text(pillar.key)} · {text(pillar.status)}</h5><Claims items={[pillar.claim]}/></div>; })}<h5>催化条件与风险</h5><Claims items={thesis.catalysts}/><Claims items={thesis.risks}/><h5>证伪条件</h5>{arr(thesis.invalidation_conditions).map((v, i) => { const c = obj(v); return <p key={i}>{text(c.condition)}；度量 {text(c.measurement)}；阈值 {text(c.threshold)}；窗口 {text(c.window)}</p>; })}<h5>后续监控</h5>{arr(thesis.monitoring_conditions).map((v, i) => <p key={i}>{text(v)}</p>)}</> : <p>{frozen.thesis_version_id ? "历史版本存在，但本次未取得可用论点正文；引用不齐或格式不可读，不将它当作有效论点。" : "未提供已保存的论点版本，没有临时生成有效论点。"}</p>}{feature ? <><p>确定性特征版本 {text(feature.payload.version)}；快照 ID {text(feature.payload.feature_snapshot_id)}；输入指纹 {text(feature.payload.input_hash)}</p><Fields value={Object.fromEntries(Object.entries(obj(feature.payload.values)).map(([k, v]) => [({ eligible_evidence_count: "当次符合条件的证据条数", eligible_quality_total: "当次符合条件的质量分合计", latest_available_at: "最近可得时间" } as Data)[k] as string ?? k, v]))}/><p>上述数值直接读取已保存的确定性特征，不由浏览器或模型重算；证据计数不是收益、估值或仓位信号。</p></> : <p>尚未生成特征快照。</p>}</details>
      <details id={`${prefix}-roles`} aria-label="两轮角色追溯"><summary>两轮观点与后续角色</summary><p>各轮与失败独立保留，不以第二轮覆盖首轮。角色观点不是风险批准。</p>{["ROUND_1", "ROUND_2"].map((stage, i) => { const step = run.steps.find(s => s.stage === stage && s.status === "COMPLETED"); return <div key={stage}><h5>第 {i + 1} 轮</h5>{step ? <><p>记录冲突数：{text(step.payload.conflict_count)}</p>{arr(step.payload.roles).map((value, j) => <Role key={j} value={value}/>)}</> : <p>此轮尚无完成记录，不能推断所有角色成功。</p>}</div>; })}{committee ? <p>委员会 {text(committee.payload.committee_session_id)}；实际轮数 {text(committee.payload.round_count)}；记录的未解决冲突数 {text(committee.payload.unresolved_conflicts)}。</p> : <p>尚无完整委员会记录。</p>}{["PORTFOLIO", "RISK_AGENT", "CIO"].map(stage => { const step = run.steps.find(s => s.stage === stage && s.status !== "RUNNING"); return step ? <Role key={stage} value={step.payload} name={label(stage === "RISK_AGENT" ? "RISK" : stage)}/> : <p key={stage}>{label(stage === "RISK_AGENT" ? "RISK" : stage)}尚无已保存产物。</p>; })}</details>
    </>}
  </section>;
}
function EvidenceBody({ payload }: {
    payload: unknown;
}) {
    if (typeof payload !== "string")
        return <p>本次没有可读正文，未访问来源补取。</p>;
    let value: unknown;
    try {
        value = JSON.parse(payload);
    }
    catch {
        return <p>保存的正文格式不可读，未作为已核实内容展示。</p>;
    }
    // Bounded plain-text rendering. Never HTML, URLs, Markdown or executable content.
    function render(v: unknown, depth: number): string { if (depth > 4)
        return "（更深内容未展开）"; if (typeof v === "string")
        return v; if (typeof v === "number" || typeof v === "boolean")
        return String(v); if (Array.isArray(v))
        return v.map(x => render(x, depth + 1)).join("\n"); if (v && typeof v === "object")
        return Object.entries(v).map(([k, x]) => `${k}：${render(x, depth + 1)}`).join("\n"); return "未记录"; }
    const body = render(value, 0);
    return <><p className="trace-body">{body.slice(0, 16000)}</p>{body.length > 16000 ? <p>正文超过展示长度，已截断；未对截断内容作结论。</p> : null}</>;
}
