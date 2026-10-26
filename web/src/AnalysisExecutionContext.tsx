import { useEffect, useRef, useState } from "react";
import { readAnalysisJson } from "./analysisReads";
import { StatusBanner } from "./ProductChrome";
import { tokenPriceLabel } from "./analysisLabels";

type Context = { run_id: string; status: "RECORDED" | "NOT_RECORDED"; receipt: null | { feature_snapshot_id: string; request_input_hash: string; runtime_input_hash: string; recorded_at: string }; valuation: null | Record<string, unknown> };
export function AnalysisExecutionContext({ runId }: { runId: string }) {
  const [data, setData] = useState<Context | null>(null), [error, setError] = useState<string | null>(null), [loading, setLoading] = useState(false);
  const generation = useRef(0), controller = useRef<AbortController | null>(null);
  useEffect(() => { ++generation.current; controller.current?.abort(); controller.current = null; setData(null); setError(null); setLoading(false); return () => { ++generation.current; controller.current?.abort(); controller.current = null; }; }, [runId]);
  async function load() {
    if (controller.current) return;
    const current = ++generation.current, next = new AbortController(); controller.current = next; setLoading(true); setError(null);
    try {
      const value = await readAnalysisJson<Context>(`/api/v1/analysis-runs/${encodeURIComponent(runId)}/execution-context`, next.signal, "读取模型前估值上下文");
      if (next.signal.aborted || current !== generation.current) return;
      if (value.run_id !== runId || !["RECORDED", "NOT_RECORDED"].includes(value.status) || (value.status === "RECORDED" && (!value.receipt?.feature_snapshot_id || !value.valuation || !/^[a-f0-9]{64}$/.test(value.receipt.runtime_input_hash)))) throw new Error("估值上下文响应不完整，未采用，请只读重试。");
      setData(value);
    } catch (reason) { if (!next.signal.aborted && current === generation.current) setError(reason instanceof Error ? reason.message : "读取失败，请重试。"); }
    finally { if (controller.current === next) controller.current = null; if (current === generation.current) setLoading(false); }
  }
  return <section className="frozen-inputs"><h3>模型前估值上下文</h3>
    <p className="hint-text">准备阶段先保存本次确定性估值，再供团队使用。取消或模型失败后仍可核对；这里只读，不重跑行情或模型，不表示完整市场特征或仓位已经就绪。</p>
    <button type="button" className="btn" disabled={loading} onClick={() => void load()}>{loading ? "正在读取估值上下文…" : data ? "重新读取估值上下文" : "核对模型前估值快照"}</button>
    <StatusBanner kind="error" text={error} />
    {data?.status === "NOT_RECORDED" ? <p>尚未保存本版模型前上下文，可能仍在准备或属于旧运行；不按当前持仓补算。</p> : null}
    {data?.status === "RECORDED" && data.receipt && data.valuation ? <>
      <p>模型前上下文已固定；保存成功不等于分析成功或投资批准。</p>
      <p>现金：{tokenPriceLabel(data.valuation.cash_balance)} · 净值：{data.valuation.nav === null ? "未知" : tokenPriceLabel(data.valuation.nav)} {String(data.valuation.base_currency)}</p>
      <p className="hint-text">业务时点：{String(data.valuation.as_of)} · 实际记录：{data.receipt.recorded_at}</p>
      <p className="hint-text">FeatureSnapshot：{data.receipt.feature_snapshot_id}<br />排队请求摘要：{data.receipt.request_input_hash}<br />模型运行输入摘要：{data.receipt.runtime_input_hash}</p>
      <details><summary>查看固定的程序计算值与缺口</summary><pre>{JSON.stringify(data.valuation, null, 2)}</pre></details>
    </> : null}
  </section>;
}
