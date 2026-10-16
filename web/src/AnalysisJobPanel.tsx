import { useEffect, useRef, useState } from "react";
import { retryAnalysis } from "./analysisSubmission";
import { apiFetch, readApiError } from "./writeApi";

type Run = { id: string; status: string; payload: Record<string, unknown>; failure_code: string | null; failure_detail: string | null; updated_at: string };
type Event = { id: string; sequence: number; stage: string; state: string; occurred_at: string };
const active = (status: string) => status === "QUEUED" || status === "RUNNING";
const stages: Record<string, string> = { QUEUED: "后台排队", PREPARING: "核对冻结输入", ROUND_ONE: "第一轮 · 五位专家独立分析", CONFLICTS: "识别观点冲突", ROUND_TWO: "第二轮 · 定向质疑与反方审查", PORTFOLIO: "组合经理评估", RISK: "风险经理评估", VALUATION_SIZING: "确定性估值与仓位计算", CIO: "最终建议与规则闸门", CANCEL_REQUESTED: "已请求取消，等待阶段边界", FINISHED: "任务结束" };
const states: Record<string, string> = { STARTED: "开始", COMPLETED: "完成", FAILED: "失败", CANCELLED: "取消", REQUESTED: "请求已记录" };

export function AnalysisJobPanel({ run, onUpdate }: { run: Run; onUpdate: (run: Run) => void }) {
  const [events, setEvents] = useState<Event[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<"cancel" | "retry" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const updateRef = useRef(onUpdate);
  updateRef.current = onUpdate;
  const mutating = useRef(false);
  const generation = useRef(0);
  const background = run.payload.execution_mode === "BACKGROUND";

  useEffect(() => {
    if (!background) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    async function poll() {
      if (mutating.current) { timer = setTimeout(() => void poll(), 2000); return; }
      const serial = ++generation.current;
      try {
        const responses = await Promise.all([
          apiFetch(`/api/v1/analysis-runs/${encodeURIComponent(run.id)}`, { signal: controller.signal }),
          apiFetch(`/api/v1/analysis-runs/${encodeURIComponent(run.id)}/progress`, { signal: controller.signal }),
        ]);
        for (const response of responses) if (!response.ok) throw new Error(await readApiError(response));
        const [detail, rows] = await Promise.all(responses.map((response) => response.json())) as [Run, Event[]];
        if (!alive) return;
        if (serial === generation.current) { updateRef.current(detail); setEvents(rows); setError(null); }
        if (active(detail.status) || serial !== generation.current) timer = setTimeout(() => void poll(), 2000);
      } catch (reason) {
        if (alive && serial === generation.current) setError(`${reason instanceof Error ? reason.message : "进度读取失败。"} 自动读取已暂停；可手动重试，不会重新调用模型。`);
      }
    }
    void poll();
    return () => { alive = false; controller.abort(); clearTimeout(timer); generation.current++; };
  }, [run.id, background, refresh]);

  async function act(kind: "cancel" | "retry") {
    if (mutating.current) return;
    mutating.current = true; generation.current++; setBusy(true); setError(null); setConfirm(null);
    try {
      if (kind === "retry") {
        const next = await retryAnalysis(run.id);
        window.location.href = `/analysis?run_id=${encodeURIComponent(next.id)}`;
      } else {
        const response = await apiFetch(`/api/v1/analysis-jobs/${encodeURIComponent(run.id)}/cancel`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
        });
        if (!response.ok) throw new Error(await readApiError(response));
        generation.current++; updateRef.current(await response.json() as Run);
        setNotice("取消请求已记录。排队任务不再执行；运行中任务在阶段边界停止，上游已发请求可能仍计费。");
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "操作结果未确认，请先刷新核对，不要重复发起。"); }
    finally { mutating.current = false; setBusy(false); setRefresh((value) => value + 1); }
  }

  if (!background) return <p className="hint-text">这是旧同步运行，未记录新版实时阶段事件；不追补或伪造进度。</p>;
  return <section aria-label="后台任务与真实进度">
    <h3>后台任务与真实进度</h3>
    <p className="context-note">可离开页面，任务由 Worker 继续；刷新后按运行 ID 找回。这里只展示实际记录的事件，不推算百分比。“完成”表示阶段结束，不等于观点可信或风控通过。</p>
    <p role="status">当前阶段：{stages[String(run.payload.stage)] ?? "等待工作者记录"}{run.status === "QUEUED" ? "。尚未调用模型；长时间排队请检查 Worker 是否运行。" : ""}</p>
    {typeof run.payload.retry_of === "string" ? <p className="hint-text">这是重新发起的新运行，原报告保持不变。<a href={`/analysis?run_id=${encodeURIComponent(run.payload.retry_of)}`}>查看原运行 →</a></p> : null}
    {notice ? <p role="status">{notice}</p> : null}
    {error ? <p role="alert" className="banner banner-error">{error}</p> : null}
    <div className="button-row"><button type="button" className="btn" disabled={busy} onClick={() => setRefresh((value) => value + 1)}>刷新任务进度</button>
      {active(run.status) ? <button type="button" className="btn" disabled={busy || run.payload.stage === "CANCEL_REQUESTED"} onClick={() => setConfirm("cancel")}>请求取消</button> : null}
      {run.status === "FAILED" || run.status === "CANCELLED" ? <button type="button" className="btn" disabled={busy} onClick={() => setConfirm("retry")}>重新发起新运行</button> : null}
    </div>
    {confirm ? <section aria-label="任务操作确认" className="context-note"><p>{confirm === "cancel" ? "确认取消？已发出的上游调用可能完成、修复和计费；仅阻止后续阶段，不撤销历史。" : "将新建一次分析，可能再次计费。沿用原证据 ID 并重新验证有效性，重新读取当前组合、政策和模型配置；不会修改原报告。进程中断的上游费用可能尚不确定，请先核对。"}</p><div className="button-row"><button type="button" className="btn" onClick={() => setConfirm(null)}>暂不操作</button><button type="button" className="btn primary" disabled={busy} onClick={() => void act(confirm)}>{confirm === "cancel" ? "确认请求取消" : "确认新建并调用模型"}</button></div></section> : null}
    {busy ? <p role="status">正在保存操作，请勿重复提交…</p> : null}
    {events.length ? <ol className="tip-list">{events.map((event) => <li key={event.id}>{new Date(event.occurred_at).toLocaleTimeString("zh-CN")} · {stages[event.stage] ?? event.stage} · {states[event.state] ?? event.state}</li>)}</ol> : <p className="hint-text">尚无可读取的阶段记录。</p>}
  </section>;
}
