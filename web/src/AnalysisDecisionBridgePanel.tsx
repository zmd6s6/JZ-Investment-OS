import { useEffect, useRef, useState } from "react";
import { apiFetch, readApiError } from "./writeApi";
import "./analysis-decision-bridge.css";

type Qualification = { qualification_id: string; portfolio_id: string; instrument_id: string; strategy_version_id: string; source_name: string; source_kind: string; created_at: string; expires_at: string };
type Preparation = { status: "BLOCKED" | "PENDING_APPROVAL"; decision_id: string | null; request_id: string; revision: number; qualification_id: string | null; blockers: string[]; gates: Record<string, string>; simulation_only: true; execution_allowed: false; auto_trade: false };
export type BridgeRun = { run_id: string; portfolio_id: string; instrument_id: string; status: string; input_hash: string | null };

async function read<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(url, { ...init, signal: init?.signal ?? AbortSignal.timeout(20000) });
  if (!response.ok) throw new Error(await readApiError(response));
  return response.json() as Promise<T>;
}
function validate(value: Preparation): Preparation {
  if (!["BLOCKED", "PENDING_APPROVAL"].includes(value?.status) || !Number.isInteger(value.revision) || value.revision < 1 || !Array.isArray(value.blockers) || value.simulation_only !== true || value.auto_trade !== false || value.execution_allowed !== false || (value.status === "PENDING_APPROVAL") !== !!value.decision_id) throw new Error("决策准备响应不符合人工审阅边界，请刷新核对。");
  return value;
}
const labels: Record<string, string> = {
  DECISION_GATE_EVIDENCE_NOT_IN_FROZEN_ANALYSIS: "资格资料不在本次原始冻结证据内，请保留原运行并重新分析。",
  DECISION_STRATEGY_NOT_APPROVED: "固定策略版本未获得明确人工批准，不能自行激活。",
  DECISION_PENDING_EXPOSURE_CHANGED: "其他待成交批准改变了容量，原测算不能继续使用。",
  DECISION_UNRESOLVED_HIGH_OR_CRITICAL_AGENT_RISK: "存在尚未解决的高或严重风险观点，不能增加暴露。",
  DECISION_RISK_REDUCTION_CONFIRMATION_REQUIRED: "风险否决下的减持或退出需要单独确认降风险例外。",
  SCHEDULED_SHADOW_CANNOT_CREATE_INVESTMENT_DECISION: "每日任务只授权影子分析和费用，不能升级为可审批决策。",
};

export function AnalysisDecisionBridgePanel({ run }: { run: BridgeRun }) {
  const [sources, setSources] = useState<Qualification[]>([]), [history, setHistory] = useState<Preparation[]>([]);
  const [selected, setSelected] = useState(""), [actor, setActor] = useState(""), [confirmed, setConfirmed] = useState(false), [reduction, setReduction] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const epoch = useRef(0), request = useRef<{ key: string; id: string } | null>(null);
  const root = `/api/v1/analysis/runs/${run.run_id}/decision-preparations`;
  const last = history.at(-1), existing = history.find(item => item.status === "PENDING_APPROVAL");
  const terminal = ["SUCCEEDED", "DEGRADED"].includes(run.status) && !!run.input_hash;
  useEffect(() => {
    const sequence = ++epoch.current, controller = new AbortController();
    setSources([]); setHistory([]); setSelected(""); setActor(""); setConfirmed(false); setReduction(false); setError(null); setLoading(true); setBusy(false); request.current = null;
    void Promise.all([
      read<Qualification[]>(`/api/v1/analysis/decision-qualifications?portfolio_id=${encodeURIComponent(run.portfolio_id)}&instrument_id=${encodeURIComponent(run.instrument_id)}`, { signal: controller.signal }),
      read<Preparation[]>(root, { signal: controller.signal }),
    ]).then(([choices, records]) => {
      if (!Array.isArray(choices) || choices.some(item => item.portfolio_id !== run.portfolio_id || item.instrument_id !== run.instrument_id || !item.qualification_id) || !Array.isArray(records)) throw new Error("资格或历史响应与当前分析不符。");
      const saved = records.map(validate);
      if (epoch.current === sequence) { setSources(choices); setHistory(saved); }
    }).catch(reason => { if (epoch.current === sequence && !controller.signal.aborted) setError(reason instanceof Error ? reason.message : "读取失败，请刷新核对。"); })
      .finally(() => { if (epoch.current === sequence) setLoading(false); });
    return () => { epoch.current++; controller.abort(); };
  }, [root, run.portfolio_id, run.instrument_id, refresh]);

  async function prepare() {
    if (!terminal || !selected || !actor.trim() || !confirmed || busy || loading || existing) return;
    const sequence = epoch.current;
    const command = { schema_version: "prepare-analysis-decision-1.0", run_id: run.run_id, qualification_id: selected, expected_input_hash: run.input_hash, expected_revision: last?.revision ?? 0, actor_id: actor, confirm_preparation: true, confirm_risk_reduction_exception: reduction };
    const key = JSON.stringify(command);
    if (request.current?.key !== key) request.current = { key, id: crypto.randomUUID() };
    setBusy(true); setError(null);
    try {
      const result = validate(await read<Preparation>(root, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...command, request_id: request.current.id }) }));
      if (result.request_id !== request.current?.id || result.qualification_id !== selected) throw new Error("保存回执与明确请求不符，请刷新历史核对。");
      if (epoch.current === sequence) { setHistory(previous => [...previous.filter(item => item.request_id !== result.request_id), result]); setConfirmed(false); request.current = null; }
    } catch (reason) { if (epoch.current === sequence) setError(reason instanceof Error ? reason.message : "结果未知，请刷新历史后重试；不会自动提交。"); }
    finally { if (epoch.current === sequence) setBusy(false); }
  }
  return <section className="analysis-decision-bridge" aria-label="从分析准备人工审阅决策">
    <h3>准备人工审阅决策</h3>
    <p>原分析和影子结论保持不变。单独确认后，将从原冻结资料与固定已批准策略生成待审阅记录，不增加模型调用。准备完成后仍需在决策中心明确批准、拒绝或撤销；不会自动提交订单。</p>
    <p>当前仅支持明确合成环境的完整资格验证。没有真实已授权来源时保持阻断，不能在此选择真实阈值或激活策略。</p>
    <button type="button" disabled={loading || busy} onClick={() => setRefresh(value => value + 1)}>刷新准备历史与资格</button>
    {loading ? <p role="status">正在读取资格与不可变准备历史…</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {!terminal ? <p>请先等待本次分析正常结束并保存输入快照。</p> : null}
    {!loading && !sources.length ? <p>没有可用的完整资格快照；数值 PASS 和正面意见不能代替投资质量、时点、组合适配与授权。</p> : null}
    {existing ? <p role="status">已保存待人工审阅决策 {existing.decision_id}。<a href={`/decisions?decision_id=${encodeURIComponent(existing.decision_id!)}`}>前往决策中心审阅</a></p> : <>
      <label>原时点固定资格<select aria-label="原时点固定资格" value={selected} onChange={event => setSelected(event.target.value)} disabled={loading || busy}><option value="">请选择完整资格快照</option>{sources.map(item => <option key={item.qualification_id} value={item.qualification_id}>{item.source_name} · {item.source_kind} · 策略 {item.strategy_version_id}</option>)}</select></label>
      <label>记录操作者<input aria-label="准备决策操作者" value={actor} onChange={event => setActor(event.target.value)} disabled={busy} /></label>
      <label><input type="checkbox" checked={reduction} onChange={event => setReduction(event.target.checked)} disabled={busy} />仅在原提案为减持或退出时，明确记录风险否决下的降风险例外；不覆盖增仓否决。</label>
      <label><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} disabled={busy} />我确认只准备待审阅记录，尚未批准投资或订单。</label>
      <button type="button" disabled={!terminal || loading || busy || !selected || !actor.trim() || !confirmed} onClick={() => void prepare()}>{busy ? "正在核验并保存…" : "确认准备待审阅决策"}</button>
    </>}
    {history.map(item => <div key={item.request_id}><p>准备记录 #{item.revision}：{item.status === "BLOCKED" ? "已阻断，未创建决策" : "已创建待人工审阅记录"}</p>{Object.entries(item.gates).map(([gate, outcome]) => <p key={gate}>{gate}：{outcome}</p>)}{item.blockers.map(code => <p key={code}>{labels[code] ?? "完整资格或风险条件未满足，请核对原资料。"} <code>{code}</code></p>)}</div>)}
  </section>;
}
