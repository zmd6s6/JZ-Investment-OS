import { useEffect, useRef, useState } from "react";
import { apiFetch, readApiError } from "./writeApi";

type PortfolioChoice = { portfolio_id: string; name: string; base_currency: string };

export function AnalysisStartDialog({ label, portfolio, onCancel, onConfirm }: {
  label: string;
  portfolio?: PortfolioChoice;
  onCancel: () => void;
  onConfirm: (portfolioId: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [choices, setChoices] = useState<PortfolioChoice[]>(portfolio ? [portfolio] : []);
  const [selectedId, setSelectedId] = useState(portfolio?.portfolio_id ?? "");
  const [loading, setLoading] = useState(!portfolio);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const element = dialog.current;
    if (typeof element?.showModal === "function") element.showModal();
    else element?.setAttribute("open", "");
    return () => { if (typeof element?.close === "function") element.close(); };
  }, []);

  useEffect(() => {
    if (portfolio) return;
    let cancelled = false;
    void (async () => {
      try {
        const response = await apiFetch("/api/v1/portfolios");
        if (!response.ok) throw new Error(await readApiError(response));
        const rows = await response.json() as PortfolioChoice[];
        if (!cancelled) setChoices(rows);
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "读取组合失败，请关闭后重试。");
      } finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [portfolio]);

  return (
    <dialog ref={dialog} className="access-dialog" aria-labelledby="analysis-start-title" onCancel={(event) => { event.preventDefault(); onCancel(); }}>
      <form onSubmit={(event) => { event.preventDefault(); if (selectedId && !loading) onConfirm(selectedId); }}>
        <div className="panel-header"><div><p className="eyebrow">启动前确认</p><h2 id="analysis-start-title">分析 {label}</h2></div><button type="button" className="btn ghost" onClick={onCancel}>关闭</button></div>
        <label className="field"><span>分析所用组合</span><select value={selectedId} disabled={Boolean(portfolio) || loading} onChange={(event) => setSelectedId(event.target.value)} required><option value="">请选择组合上下文</option>{choices.map((choice) => <option key={choice.portfolio_id} value={choice.portfolio_id}>{choice.name} · {choice.base_currency}</option>)}</select></label>
        {loading ? <p role="status">正在读取组合…</p> : null}
        {error ? <p role="alert" className="banner banner-error">{error}</p> : null}
        {!loading && choices.length === 0 ? <p className="context-note">分析需要现金与持仓上下文。<a href="/portfolio">先创建一个组合 →</a>，不必持有此标的。</p> : null}
        <ul className="tip-list">
          <li>使用设置中的模型与角色映射，可能调用付费模型；受已配置预算约束。<a href="/settings#models">检查模型与预算</a>。</li>
          <li>本轮读取该标的已入库证据，不会自动抓取新闻。缺证据会失败关闭，不编造材料。</li>
          <li>可能需要 1–2 分钟；请求中请保留页面。当前不支持取消正在执行的模型请求。</li>
          <li>缺行情可阅读研究意见，但不能据此计算完整估值或买入数量；结果不产生订单。</li>
        </ul>
        <div className="dialog-actions"><button type="button" className="btn" onClick={onCancel}>暂不分析</button><button type="submit" className="btn primary" disabled={loading || !selectedId || Boolean(error)}>确认启动分析</button></div>
      </form>
    </dialog>
  );
}
