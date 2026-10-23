import { useEffect, useState } from "react";
import { readAnalysisJson } from "./analysisReads";
import { tokenPriceLabel } from "./analysisLabels";

const statuses: Record<string, string> = { SUCCEEDED: "报价齐全", PARTIAL: "部分缺价，继续下一来源", NO_DATA: "未取得可用报价", FAILED: "来源调用或报价校验失败", CONFIGURATION_CHANGED: "档案已改变，停止继续读取", CREDENTIAL_MISSING: "凭据不可用，停止继续读取" };
type Quote = { instrument_id: string; reference_price: string; currency: string; as_of: string };
type Attempt = { profile_id: string; name: string; provider_type: string; rank: number; status: string; queries: string[]; quotes?: Quote[] };
type AttemptEvent = { attempt_id: string; occurred_at: string; attempt: Attempt };

export function DurableMarketAudit({ runId, active, tracked, fallback }: { runId: string; active: boolean; tracked: boolean; fallback: unknown }) {
  const [events, setEvents] = useState<AttemptEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (!tracked) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    setError(null);
    const read = async () => {
      try {
        const result = await readAnalysisJson<AttemptEvent[]>(`/api/v1/analysis-runs/${encodeURIComponent(runId)}/market-attempts`, controller.signal, "读取行情调用记录");
        if (!Array.isArray(result)) throw new Error("行情记录格式异常，请重试读取。");
        if (!controller.signal.aborted) { setEvents(result); setError(null); }
      } catch (reason) {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "行情记录暂不可读，不能判断实际调用。");
      } finally {
        if (active && !controller.signal.aborted) timer = setTimeout(() => void read(), 3000);
      }
    };
    void read();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [runId, active, tracked, refresh]);
  if (!tracked) return <AnalysisMarketAudit value={fallback} />;
  const latest = new Map<string, AttemptEvent>();
  events?.forEach((event) => latest.set(event.attempt_id, event));
  return <section aria-label="持久化行情调用记录"><h4>行情调用记录</h4>
    {fallback && typeof fallback === "object" && (fallback as { selection?: string }).selection === "NONE" ? <p className="context-note">本次未选择行情源，没有自动调用已启用来源或使用合成报价。</p> : null}
    <p className="hint-text">调用意图先保存，结果另行追加，取消或中断也保留。开始记录不证明上游已收到请求，也不表示费用为零。</p>
    {error ? <p role="alert">{error} 已有记录保留；不会重发行情或模型请求。</p> : null}
    <button type="button" className="btn ghost" onClick={() => setRefresh((value) => value + 1)}>重新读取行情记录</button>
    {events === null ? <p>{error ? "当前记录未知。" : "正在读取行情记录…"}</p> : latest.size === 0 ? <p>暂未记录行情尝试；可能尚未到行情阶段，不代表来源可用或整个分析未计费。</p> : <ol className="tip-list">{Array.from(latest.values()).map((event) => <li key={event.attempt_id}>
      <strong>第 {event.attempt.rank + 1} 档 · {event.attempt.name}</strong>
      <p>{event.attempt.status === "STARTED" ? "已保存调用意图，结果未知；可能未发出、处理中或已中断，请核对后再决定是否新建运行。" : statuses[event.attempt.status] ?? event.attempt.status}；查询：{event.attempt.queries.join("、")}</p>
      <p className="hint-text">记录时间 {event.occurred_at}</p>
      {event.attempt.quotes?.map((q) => <p className="hint-text" key={q.instrument_id}>标的 {q.instrument_id} · {tokenPriceLabel(q.reference_price)} {q.currency} · 行情时点 {q.as_of}</p>)}
    </li>)}</ol>}
  </section>;
}

export function AnalysisMarketAudit({ value }: { value: unknown }) {
  if (!value || typeof value !== "object") return <p className="hint-text">本报告未记录行情尝试，可能是旧版或在结果保存前终止；不能据此判断来源未调用，不根据当前设置追补。</p>;
  const audit = value as { selection?: string; attempts?: Attempt[] };
  if (audit.selection === "NONE") return <p className="context-note">本次未选择行情源，没有自动调用已启用来源或使用合成报价。</p>;
  const attempts = Array.isArray(audit.attempts) ? audit.attempts : [];
  return <details><summary>行情来源实际尝试 · {attempts.length} 项</summary><p className="hint-text">只记录实际调用和校验结果，顺序来自本次确认；未列出的来源没有尝试。第二项及之后取得的报价标记为降级。</p>{attempts.length ? <ol className="tip-list">{attempts.map((a) => <li key={`${a.rank}-${a.profile_id}`}><strong>第 {a.rank + 1} 档 · {a.name} · {a.provider_type}</strong><p>{statuses[a.status] ?? a.status}；查询：{a.queries.join("、")}</p>{a.quotes?.map((q) => <p className="hint-text" key={q.instrument_id}>标的 {q.instrument_id} · {tokenPriceLabel(q.reference_price)} {q.currency} · 行情时点 {q.as_of}</p>)}</li>)}</ol> : <p>尚无实际行情尝试；不表示来源可用。</p>}</details>;
}
