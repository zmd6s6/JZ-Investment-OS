import { useEffect, useRef, useState } from "react";
import { DecisionCenterTrace } from "./DecisionCenterTrace";
import { Panel, ProductChrome, StatusBanner } from "./ProductChrome";
import { apiFetch, readApiError } from "./writeApi";
import "./decision-center.css";

type Card = { decision_id: string; portfolio_id: string; instrument_id: string; symbol: string; action: string; state: string; revision: number; created_at: string; blockers: string[] };
type Claim = { text: string; evidence_ids: string[] };
type Execution = { quantity: string; price: string; fees: string; executed_at: string; references: string[]; note: string; status: string; approval_id: string };
type History = { request_id: string; revision: number; action: string; state: string; actor_id: string; comment: string; occurred_at: string; execution?: Execution };
type Detail = { schema_version: string; decision: Card; as_of: string; mode: string; auto_trade: false; journal: { content_hash: string; input_snapshot_hash: string; reasons: Claim[]; risks: Claim[]; core_action: string; tactical_action: string; position_before: Record<string, string>; position_after_proposed: Record<string, string>; unknowns: string[]; dissent: string[]; watch_conditions: string[]; invalidation_conditions: string[]; prompt_bundle_version: string; formula_version: string }; lineage: { thesis_version_id: string | null; policy_version_id: string; strategy_version_id: string; risk_assessment_id: string | null; risk_veto: boolean | null; risk_codes: string[]; risk_expires_at: string | null; sizing_run_id: string | null; sizing_input: { reference_price?: string } | null; evidence: { evidence_id: string; source: string; locator: string; available_at: string; expires_at: string | null; content_hash: string }[] }; history: History[]; approval_id: string | null; approval_expires_at: string | null; approved_quantity: string | null; filled_quantity: string; remaining_quantity: string | null; allowed_actions: string[] };

const states: Record<string, string> = { PENDING_APPROVAL: "等待明确人工决定", APPROVED: "已批准，尚未登记成交", REJECTED: "已拒绝", CANCELLED: "已撤销", EXPIRED: "批准已到期", PARTIALLY_EXECUTED: "已登记部分成交", EXECUTED: "已登记全部成交", DRAFT: "草稿，不可批准", RISK_VETOED: "风险否决" };
const labels: Record<string, string> = { APPROVE: "批准", REJECT: "拒绝", REVOKE: "撤销未成交批准", RECORD_EXECUTION: "登记外部手工成交事实" };
const reasons: Record<string, string> = { EVIDENCE_MISSING: "缺少证据", EVIDENCE_STALE_OR_UNAVAILABLE: "证据已过期或当时不可用", THESIS_MISSING: "缺少固定论点版本", RISK_MISSING_OR_EXPIRED: "风险评估缺失、过期或引用不符", RISK_VETO: "风险否决不可覆盖", POLICY_MISSING: "缺少政策版本", POLICY_NOT_APPROVED: "政策未获有效人工批准，测试默认值不能授权交易", POLICY_CHANGED: "当前政策已改变，须重新生成结论", POLICY_INVALID: "政策结构不完整", SIZING_MISSING_OR_MISMATCH: "仓位计算缺失或引用不符", SIZING_INPUT_INVALID: "仓位输入或输出不完整", PORTFOLIO_INPUT_CHANGED: "当前现金或分仓与计算时不符", STRATEGY_NOT_APPROVED: "策略未处于已批准生效状态", LEGACY_ACTION_HISTORY_REQUIRES_REVIEW: "旧人工历史缺完整状态事件，请保留历史并重新审阅" };
const number = (value: string | null | undefined) => value?.replace(/(\.\d*?[1-9])0+$/, "$1").replace(/\.0+$/, "") ?? "未提供";

async function read<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 15000);
  try {
    const response = await apiFetch(path, { ...init, signal: controller.signal });
    if (!response.ok) throw new Error(await readApiError(response));
    return await response.json() as T;
  } catch (error) {
    if (controller.signal.aborted) throw new Error("请求超时，操作结果未知；请刷新核对后重试，不会自动提交。");
    throw error;
  } finally { window.clearTimeout(timer); }
}
function validDetail(value: Detail, id: string): Detail {
  const arrays = [value?.allowed_actions, value?.history, value?.decision?.blockers, value?.lineage?.evidence, value?.lineage?.risk_codes, value?.journal?.reasons, value?.journal?.risks, value?.journal?.unknowns, value?.journal?.dissent, value?.journal?.watch_conditions, value?.journal?.invalidation_conditions];
  if (value?.schema_version !== "1.0" || value.decision?.decision_id !== id || !Number.isInteger(value.decision?.revision) || value.auto_trade !== false || value.mode !== "RECORD_ONLY_NO_BROKER" || arrays.some(item => !Array.isArray(item)) || !value.journal?.position_before || !value.journal?.position_after_proposed || value.allowed_actions.some(action => !(action in labels))) throw new Error("决策协议或编号不符，请刷新。未启用任何操作。");
  return value;
}

export function DecisionCenterPage() {
  const [cards, setCards] = useState<Card[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [selected, setSelected] = useState("");
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [actor, setActor] = useState("");
  const [comment, setComment] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");
  const [fees, setFees] = useState("");
  const [executedAt, setExecutedAt] = useState("");
  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");
  const sequence = useRef(0);
  const listSequence = useRef(0);
  const currentId = useRef("");
  const request = useRef<{ key: string; id: string } | null>(null);

  async function refreshList() {
    const seq = ++listSequence.current;
    sequence.current++; setDetail(null); setSelected(""); currentId.current = ""; setConfirmed(false);
    setLoading(true); setError(null);
    try {
      const value = await read<Card[]>("/api/v1/decision-center");
      if (!Array.isArray(value) || value.some(card => !card.decision_id || !Array.isArray(card.blockers) || !Number.isInteger(card.revision))) throw new Error("决策列表协议不符");
      if (seq === listSequence.current) setCards(value);
    } catch (e) { if (seq === listSequence.current) { setCards([]); setError(e instanceof Error ? e.message : "读取失败，请刷新"); } }
    finally { if (seq === listSequence.current) setLoading(false); }
  }
  useEffect(() => { void refreshList(); return () => { sequence.current++; listSequence.current++; }; }, []);

  async function open(id: string) {
    const seq = ++sequence.current;
    currentId.current = id; setSelected(id); setDetail(null); setConfirmed(false); setMessage(null); setError(null); request.current = null;
    try {
      const value = validDetail(await read<Detail>(`/api/v1/decision-center/${id}`), id);
      if (seq === sequence.current && currentId.current === id) setDetail(value);
    } catch (e) { if (seq === sequence.current) setError(e instanceof Error ? e.message : "详情读取失败，不能进行操作"); }
  }
  async function act(action: string) {
    if (!detail || !confirmed || !actor.trim() || !comment.trim() || busy || !detail.allowed_actions.includes(action)) return;
    const id = detail.decision.decision_id, seq = sequence.current;
    const command: Record<string, unknown> = { expected_revision: detail.decision.revision, actor_id: actor, comment, confirmed: true };
    if (action === "RECORD_EXECUTION") {
      const time = new Date(executedAt);
      if (!quantity || !price || !fees || !reference.trim() || !note.trim() || !Number.isFinite(time.getTime())) { setError("请填写完整数量、价格、费用（可为0）、实际成交时间、外部引用与备注。"); return; }
      Object.assign(command, { approval_id: detail.approval_id, quantity, price, fees, executed_at: time.toISOString(), external_reference: reference, note });
    }
    const key = JSON.stringify({ id, action, command });
    if (request.current?.key !== key) request.current = { key, id: crypto.randomUUID() };
    const endpoint = { APPROVE: "approve", REJECT: "reject", REVOKE: "revoke", RECORD_EXECUTION: "record-execution" }[action];
    setBusy(true); setError(null); setMessage(null);
    try {
      const value = validDetail(await read<Detail>(`/api/v1/decision-center/${id}/${endpoint}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...command, request_id: request.current.id }) }), id);
      if (seq !== sequence.current || currentId.current !== id) return;
      setDetail(value); setCards(old => old.map(card => card.decision_id === id ? value.decision : card));
      setConfirmed(false); request.current = null;
      setMessage(`${labels[action]}已保存，版本 ${value.decision.revision}。没有提交任何订单；批准不等于成交。`);
      if (action === "RECORD_EXECUTION") { setQuantity(""); setFees(""); setExecutedAt(""); setReference(""); setNote(""); }
    } catch (e) { if (seq === sequence.current && currentId.current === id) { setError(`操作未确认，请刷新核对；重试相同输入会复用请求编号。${e instanceof Error ? e.message : ""}`); setConfirmed(false); } }
    finally { if (seq === sequence.current) setBusy(false); }
  }
  const visible = cards.filter(card => !filter || card.state === filter);
  return <ProductChrome eyebrow="人工决定与不可变日志" title="决策中心" subtitle="SIMULATION / NO AUTO TRADE · 批准与记录是不同动作。本页仅记录人工决定和外部手工事实，不连接券商或提交订单。">
    <div className="decision-center">
    <StatusBanner kind="error" text={error} /><StatusBanner kind="ok" text={message} />
    <Panel title="从哪里开始"><ol><li>先查看结论、证据、Core/Tactical、风险与确定性数量，再填写自己的归属名称与理由并明确确认。</li><li>批准期限来自固定政策，Risk Veto、缺项、输入变化或到期不能被批准覆盖。</li><li>只有在系统外已完成手工动作后才登记事实；填写真实时间和费用，不把批准按钮理解为交易。</li></ol><p>当前<a href="/analysis">团队分析</a>仅产生受限 ShadowDecision（Risk UNKNOWN / Sizing BLOCKED），不会出现在可审批列表中，也不能转成订单。没有完整 Decision 时本页如实为空；测试默认政策不是交易授权。</p></Panel>
    <Panel title="决策列表（最近100条）"><button type="button" disabled={busy || loading} onClick={() => void refreshList()}>刷新决策列表</button><label>按状态筛选<select aria-label="决策状态筛选" disabled={busy} value={filter} onChange={e => setFilter(e.target.value)}><option value="">全部状态</option>{Object.entries(states).map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></label>{loading ? <p role="status">正在读取决策…</p> : null}{!visible.length && !loading ? <p>没有符合条件的完整决策。影子结论和失败分析不是待批准交易。</p> : null}<ul>{visible.map(card => <li key={card.decision_id}><button type="button" disabled={busy} onClick={() => void open(card.decision_id)} aria-pressed={selected === card.decision_id}>{card.symbol} · {card.action} · {states[card.state] ?? card.state}</button><small> {card.created_at} · 版本{card.revision}</small></li>)}</ul></Panel>
    {selected ? <Panel title="决策详情与审阅"><button type="button" disabled={busy} onClick={() => void open(selected)}>重新读取当前决策</button>{!detail ? <p>等待有效详情，人工操作尚未启用。</p> : <>
      <h3>{detail.decision.symbol} · {detail.decision.action} · {states[detail.decision.state] ?? detail.decision.state}</h3><p>Decision {detail.decision.decision_id} · 组合 {detail.decision.portfolio_id}<br />读取时点 {detail.as_of} · 当前版本 {detail.decision.revision}</p>
      <h4>不可覆盖的条件</h4>{detail.decision.blockers.length ? <ul>{detail.decision.blockers.map(code => <li key={code}>{reasons[code] ?? "条件未齐，不能批准或登记"} <small>{code}</small></li>)}</ul> : <p>本次读取的完整性条件通过，提交时仍由服务端重新核对。</p>}
      <p>风险 {detail.lineage.risk_veto === null ? "未知" : detail.lineage.risk_veto ? "VETO 否决" : "无 Veto（以固定评估为准）"}；有效至 {detail.lineage.risk_expires_at ?? "未提供"}。{detail.lineage.risk_codes.join("、")}</p>
      <h4>理由与风险（外部资料均不可信）</h4>{[...detail.journal.reasons, ...detail.journal.risks].map((claim, i) => <p key={i}>{claim.text}<br /><small>引用 {claim.evidence_ids.join("、")}</small></p>)}<h4>Core / Tactical</h4><p>Core动作 {detail.journal.core_action}，Tactical动作 {detail.journal.tactical_action}</p><ul>{["core", "tactical", "total"].map(bucket => <li key={bucket}>{bucket} 权重：{number(detail.journal.position_before[bucket])} → {number(detail.journal.position_after_proposed[bucket])}</li>)}</ul>
      <p>确定性总量 {number(detail.approved_quantity)}，累计登记 {number(detail.filled_quantity)}，剩余 {number(detail.remaining_quantity)}；参考价 {number(detail.lineage.sizing_input?.reference_price)}。当前不提供价格容差，偏离参考价须重新生成并批准决策。</p>
      <DecisionCenterTrace lineage={detail.lineage} />
      <h4>未知、反方和条件</h4><ul>{[...detail.journal.unknowns, ...detail.journal.dissent, ...detail.journal.watch_conditions, ...detail.journal.invalidation_conditions].map((value, i) => <li key={i}>{value}</li>)}</ul>
      <details><summary>固定版本、来源与证据时间</summary><p>Thesis {detail.lineage.thesis_version_id ?? "缺失"}<br />Policy {detail.lineage.policy_version_id}<br />Strategy {detail.lineage.strategy_version_id}<br />Risk {detail.lineage.risk_assessment_id ?? "缺失"}<br />Sizing {detail.lineage.sizing_run_id ?? "缺失"}<br />Prompt {detail.journal.prompt_bundle_version} · Formula {detail.journal.formula_version}<br />原结论hash {detail.journal.content_hash}<br />输入hash {detail.journal.input_snapshot_hash}</p>{detail.lineage.evidence.map(e => <p key={e.evidence_id}>{e.source} · {e.evidence_id}<br />出处 {e.locator}（仅显示，不访问）<br />可得 {e.available_at} · 到期 {e.expires_at ?? "未提供"}<br />hash {e.content_hash}</p>)}</details>
      <h4>人工动作与成交历史</h4>{!detail.history.length ? <p>尚无本中心保存的人工动作。</p> : <ol>{detail.history.map(item => <li key={item.request_id}>{labels[item.action]} · {item.actor_id} · {item.occurred_at} · {states[item.state] ?? item.state}<p>{item.comment}</p>{item.execution ? <p>手工成交量 {number(item.execution.quantity)} · 价 {number(item.execution.price)} · 费用 {number(item.execution.fees)}<br />实际成交 {item.execution.executed_at} · 批准 {item.execution.approval_id}<br />外部引用 {item.execution.references.join("、")}<br />备注 {item.execution.note}</p> : null}</li>)}</ol>}
      <p>当前批准 {detail.approval_id ?? "无有效批准"}；到期 {detail.approval_expires_at ?? "无"}。</p>
      <fieldset disabled={busy || !detail.allowed_actions.length}><legend>明确人工动作（需要写入令牌）</legend><label>人工归属名称<input aria-label="人工归属名称" value={actor} maxLength={255} onChange={e => { setActor(e.target.value); setConfirmed(false); }} /></label><label>本次人工理由<textarea aria-label="本次人工理由" value={comment} maxLength={1000} onChange={e => { setComment(e.target.value); setConfirmed(false); }} /></label>
        {detail.allowed_actions.includes("RECORD_EXECUTION") ? <details open><summary>仅登记已完成的外部手工成交</summary><label>本次成交数量<input aria-label="本次成交数量" inputMode="decimal" value={quantity} onChange={e => { setQuantity(e.target.value); setConfirmed(false); }} /></label><label>本次成交价格<input aria-label="本次成交价格" inputMode="decimal" value={price} onChange={e => { setPrice(e.target.value); setConfirmed(false); }} /></label><label>本次费用<input aria-label="本次费用" inputMode="decimal" value={fees} onChange={e => { setFees(e.target.value); setConfirmed(false); }} /></label><label>实际成交时间（含本地时区）<input aria-label="实际成交时间" type="datetime-local" step="0.001" value={executedAt} onChange={e => { setExecutedAt(e.target.value); setConfirmed(false); }} /></label><label>外部成交引用<input aria-label="外部成交引用" value={reference} onChange={e => { setReference(e.target.value); setConfirmed(false); }} /></label><label>成交备注<textarea aria-label="成交备注" value={note} onChange={e => { setNote(e.target.value); setConfirmed(false); }} /></label></details> : null}
        <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />我已审阅当前版本与风险，确认这是本人明确动作；不要求系统发送订单。</label>{detail.allowed_actions.map(action => <button key={action} type="button" disabled={!confirmed || !actor.trim() || !comment.trim()} onClick={() => void act(action)}>{busy ? "正在保存，请勿重复提交…" : labels[action]}</button>)}
      </fieldset>{!detail.allowed_actions.length ? <p>当前没有合法人工操作；历史可继续审阅。</p> : null}
    </>}</Panel> : null}
    </div>
  </ProductChrome>;
}
