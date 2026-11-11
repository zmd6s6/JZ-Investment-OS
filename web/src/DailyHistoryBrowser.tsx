import { useEffect, useRef, useState } from "react";
import type { Config, Report, Task } from "./DailyRuntimePanel";
import { apiFetch } from "./writeApi";

type Audit = {
  report_id: string; task_run_id: string; schedule_id: string; revision_id: string;
  recorded_at: string; usable_until: string; phase: string; content_hash: string;
  availability: "AVAILABLE" | "EXPIRED" | "INVALID";
};
type Kind = "configurations" | "runs" | "history";
const root = "/api/v1/runtime/daily";
const uuid = (value: string) => /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(value);
const sectionNames = { action_required: "需要处理", hold_watch: "持有 / 观察", new_opportunity: "新机会", risk_veto: "风险否决", approvals: "待处理审批", data_job_degraded: "数据 / 任务异常" };

async function read<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(url, { ...init, signal: AbortSignal.timeout(15000) });
  if (!response.ok) {
    let code = "";
    try { code = (await response.json()).detail?.code ?? ""; } catch { /* No raw errors. */ }
    if (code === "DAILY_REPORT_EXPIRED_HISTORY_PRESERVED") throw new Error("日报正文已过期，仅保留审计摘要。");
    if (response.status === 404) throw new Error("未找到这条每日记录，请核对编号。");
    if (response.status === 409) throw new Error("授权版本已变化，请刷新详情后重新核对并确认。");
    throw new Error("每日历史读取或操作未确认，请刷新核对后明确重试。");
  }
  return await response.json() as T;
}

export function DailyHistoryBrowser() {
  const [kind, setKind] = useState<Kind>("configurations");
  const [offset, setOffset] = useState(0), [rows, setRows] = useState<(Config | Task | Audit)[]>([]);
  const [id, setId] = useState(""), [config, setConfig] = useState<Config | null>(null);
  const [task, setTask] = useState<Task | null>(null), [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null), [message, setMessage] = useState<string | null>(null);
  const [working, setWorking] = useState(false), [confirmed, setConfirmed] = useState(false);
  const generation = useRef(0), busy = useRef(false), modeRequest = useRef<{key: string; id: string} | null>(null);

  async function operation(action: () => Promise<void>) {
    if (busy.current) return;
    busy.current = true;
    setWorking(true); setError(null); setMessage(null); setConfirmed(false);
    try { await action(); }
    catch { setConfig(null); setReport(null); setTask(null); setError("每日历史读取或操作未确认，请刷新核对后明确重试。过期正文不会展示。"); }
    finally { busy.current = false; setWorking(false); }
  }
  async function page(selected: Kind, start: number) {
    const token = ++generation.current;
    const url = selected === "configurations" ? root : `${root}/${selected}`;
    const result = await read<(Config | Task | Audit)[]>(`${url}?offset=${start}&limit=20`);
    if (!Array.isArray(result) || result.length > 20 || result.some(row => {
      if (selected === "configurations") return !("prepared" in row) || !uuid(row.schedule_id) || !row.prepared?.command;
      if (selected === "runs") return !("status" in row) || !uuid(row.task_run_id) || !uuid(row.schedule_id);
      return !("report_id" in row) || !uuid(row.report_id) || !uuid(row.schedule_id) || !["AVAILABLE", "EXPIRED", "INVALID"].includes(row.availability);
    })) throw new Error("invalid page");
    if (token !== generation.current) return;
    setRows(result); setOffset(start); setKind(selected);
  }
  async function detail(selected: Kind, identifier: string) {
    if (!uuid(identifier)) throw new Error("invalid ID");
    setConfig(null); setTask(null); setReport(null); setConfirmed(false);
    if (selected === "configurations") {
      const value = await read<Config>(`${root}/configurations/${identifier}`);
      if (value.schedule_id !== identifier || !Number.isInteger(value.version) || !value.prepared?.members || typeof value.enabled !== "boolean" || typeof value.revoked !== "boolean") throw new Error("invalid configuration");
      setConfig(value);
    } else if (selected === "runs") {
      const value = await read<Task>(`${root}/runs/${identifier}`);
      if (value.task_run_id !== identifier) throw new Error("invalid task");
      setTask(value);
    } else {
      const value = await read<Report>(`${root}/reports/${identifier}`);
      if (value.report_id !== identifier || !Object.keys(sectionNames).every(key => Array.isArray(value[key as keyof typeof sectionNames]?.messages))) throw new Error("invalid report");
      setReport(value);
    }
    setId(identifier);
  }
  useEffect(() => {
    let active = true;
    setWorking(true);
    void page("configurations", 0).then(async () => {
      if (!active) return;
      const match = /^#daily_(report|task|configuration)-([a-f0-9-]{36})$/i.exec(window.location.hash);
      if (match) await detail(match[1] === "report" ? "history" : match[1] === "task" ? "runs" : "configurations", match[2]);
    }).catch(() => {
      if (active) setError("每日历史读取未确认，请明确刷新重试。");
    }).finally(() => { if (active) setWorking(false); });
    return () => { active = false; generation.current++; };
  }, []);

  async function mode(action: "PAUSE" | "REVOKE") {
    if (!config || !confirmed) return;
    const current = config;
    await operation(async () => {
      const key = `${current.schedule_id}/${current.version}/${action}`;
      if (modeRequest.current?.key !== key) modeRequest.current = { key, id: crypto.randomUUID() };
      const value = await read<Config>(`${root}/${current.schedule_id}/mode`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: modeRequest.current.id, expected_version: current.version, action, confirmed: true }),
      });
      if (value.schedule_id !== current.schedule_id || value.enabled || value.version !== current.version + 1 || (action === "REVOKE" && !value.revoked)) throw new Error("invalid receipt");
      await detail("configurations", current.schedule_id);
      modeRequest.current = null;
      setMessage(action === "PAUSE" ? "已暂停所选每日授权，原历史保留。" : "已永久撤销所选每日授权，原历史保留。");
    });
  }

  return <section aria-label="完整每日历史" style={{ overflowWrap: "anywhere" }}>
    <h3>完整每日历史</h3>
    <p>每页20条，按固定顺序读取。并发新增可能使跨页重复或暂缺，可刷新重查；页内数量不是历史总数。到期报告仅显示审计摘要。</p>
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    <label>每日历史类别<select disabled={working} value={kind} onChange={event => { setConfig(null); setTask(null); setReport(null); void operation(() => page(event.target.value as Kind, 0)); }}>
      <option value="configurations">授权配置</option><option value="runs">运行任务</option><option value="history">日报审计</option>
    </select></label>
    <button disabled={working} onClick={() => void operation(async () => { setConfig(null); setTask(null); setReport(null); await page(kind, 0); })}>刷新完整每日历史</button>
    <p>当前第{offset + 1}条起，本页{rows.length}条</p>
    <button disabled={working || offset === 0} onClick={() => void operation(() => page(kind, Math.max(0, offset - 20)))}>上一页每日历史</button>
    <button disabled={working || rows.length < 20} onClick={() => void operation(() => page(kind, offset + 20))}>加载更多每日历史</button>
    <ul>{rows.map(row => {
      if ("prepared" in row) return <li key={row.schedule_id}>{String(row.prepared.command.name)} · {row.enabled ? "已启用" : "已暂停"} · {row.schedule_id}<button disabled={working} onClick={() => void operation(() => detail("configurations", row.schedule_id))}>查看此授权</button></li>;
      if ("report_id" in row) return <li key={row.report_id}>{row.phase} · {row.recorded_at} · {row.availability === "EXPIRED" ? "正文已过期，审计保留" : row.availability === "INVALID" ? "正文校验失败" : "正文可读取"}<br />报告{row.report_id} · 任务{row.task_run_id} · 授权{row.schedule_id} · hash {row.content_hash}<button disabled={working || row.availability !== "AVAILABLE"} onClick={() => void operation(() => detail("history", row.report_id))}>查看此日报</button><button disabled={working} onClick={() => void operation(() => detail("configurations", row.schedule_id))}>查看关联授权</button></li>;
      return <li key={row.task_run_id}>{row.status} · {row.started_at} · {row.task_run_id}<button disabled={working} onClick={() => void operation(() => detail("runs", row.task_run_id))}>查看此任务</button></li>;
    })}</ul>
    <label>精确每日记录编号<input disabled={working} value={id} onChange={event => setId(event.target.value)} /></label>
    <button disabled={working || !uuid(id)} onClick={() => void operation(() => detail(kind, id))}>按编号读取每日记录</button>
    {config && <article aria-label="所选每日授权" ref={element => { if (window.location.hash === `#daily_configuration-${config.schedule_id}`) element?.scrollIntoView?.(); }}><h4>{String(config.prepared.command.name)}</h4><p>授权{config.schedule_id} · 版本{config.version} · {config.revoked ? "已永久撤销" : config.enabled ? "已启用" : "已暂停"} · {config.blocker ?? "当前无已知阻断"}</p><p>范围{config.prepared.members.map(member => `${member.name} ${member.symbol}`).join("、")} · 日历{config.prepared.calendar_source}/{config.prepared.calendar_version}</p><label><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />我已核对这一历史授权与版本，明确确认暂停或永久撤销</label><button disabled={working || !confirmed || config.revoked} onClick={() => void mode("PAUSE")}>暂停所选每日授权</button><button disabled={working || !confirmed || config.revoked} onClick={() => void mode("REVOKE")}>永久撤销所选每日授权</button></article>}
    {task && <article ref={element => { if (window.location.hash === `#daily_task-${task.task_run_id}`) element?.scrollIntoView?.(); }}><h4>所选每日任务</h4><p>{task.task_run_id} · {task.status} · 尝试{task.attempt} · {task.started_at} · {task.error_code ?? "无记录错误"}</p><button disabled={working} onClick={() => void operation(() => detail("configurations", task.schedule_id))}>查看任务授权</button></article>}
    {report && <article aria-label="所选每日正文" ref={element => { if (window.location.hash === `#daily_report-${report.report_id}`) element?.scrollIntoView?.(); }}><h4>所选日报{report.phase}</h4><p>{report.report_id} · 业务收盘{report.business_as_of} · 知识时点{report.as_of} · 记录{report.recorded_at}</p>{(Object.keys(sectionNames) as (keyof typeof sectionNames)[]).map(key => <section key={key}><h5>{sectionNames[key]} · {report[key].availability}</h5>{report[key].messages.map((value, index) => <p key={index}>{value}</p>)}</section>)}</article>}
    <p>SIMULATION / NO AUTO TRADE · 只读历史不触发研究，暂停和撤销仍需独立确认。</p>
  </section>;
}
