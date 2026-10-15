import { FormEvent, useCallback, useEffect, useState } from "react";

import { EmptyState, Panel, ProductChrome, StatusBanner } from "./ProductChrome";
import { InstrumentSearchBox } from "./InstrumentSearchBox";
import { AnalysisStartDialog } from "./AnalysisStartDialog";
import { apiFetch, readApiError } from "./writeApi";

type WatchlistItem = {
  watchlist_item_id: string;
  instrument_id: string;
  market: string;
  symbol: string;
  name: string;
  asset_type: string;
  currency: string;
  sector: string;
  added_at: string;
  lifecycle_state: string | null;
  thesis_state: string | null;
  data_freshness_as_of: string | null;
  data_freshness_status: string | null;
  next_monitoring_condition: string | null;
};

function guessMarket(symbol: string) {
  const s = symbol.trim();
  if (/^\d{5}$/.test(s)) return "HKEX";
  if (/^[69]/.test(s)) return "SSE";
  if (/^[03]/.test(s)) return "SZSE";
  return "SSE";
}

export function WatchlistPage() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [symbol, setSymbol] = useState("");
  const [name, setName] = useState("");
  const [market, setMarket] = useState("");
  const [assetType, setAssetType] = useState("EQUITY");
  const [currency, setCurrency] = useState("");
  const [sector, setSector] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [analysisTarget, setAnalysisTarget] = useState<WatchlistItem | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    const response = await fetch("/api/v1/watchlist");
    if (!response.ok) throw new Error("无法加载观察清单");
    setItems((await response.json()) as WatchlistItem[]);
  }, []);

  useEffect(() => {
    void load().catch((reason: unknown) =>
      setError(reason instanceof Error ? reason.message : "加载失败"),
    ).finally(() => setLoading(false));
  }, [load]);

  async function addItem(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const resolvedMarket = market || guessMarket(symbol);
      if (!resolvedMarket) throw new Error("请选择市场，或输入可识别的代码");
      const resolvedCurrency =
        currency || (resolvedMarket === "HKEX" ? "HKD" : "CNY");
      const response = await apiFetch("/api/v1/watchlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          market: resolvedMarket,
          symbol,
          name,
          asset_type: assetType || "EQUITY",
          currency: resolvedCurrency,
          sector,
        }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      setMessage("已加入观察清单");
      setSymbol("");
      setName("");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "加入失败");
    } finally {
      setBusy(false);
    }
  }

  async function removeItem(item: WatchlistItem) {
    if (busy) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const response = await apiFetch(
        `/api/v1/watchlist/${encodeURIComponent(item.market)}/${encodeURIComponent(item.symbol)}`,
        { method: "DELETE" },
      );
      if (!response.ok) throw new Error(await readApiError(response));
      setMessage(`已移除 ${item.symbol}`);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "移除失败");
    } finally {
      setBusy(false);
    }
  }

  async function analyze(item: WatchlistItem, portfolioId: string) {
    if (busy) return;
    setAnalysisTarget(null);
    setBusy(true);
    setAnalyzing(true);
    setError(null);
    setMessage(null);
    try {
      const response = await apiFetch("/api/v1/analysis-runs", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instrument_id: item.instrument_id, portfolio_id: portfolioId, source: "WATCHLIST" }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      try { sessionStorage.setItem("selected_portfolio_id", portfolioId); } catch { /* session storage is optional */ }
      window.location.href = "/analysis";
    } catch (reason) { setError(reason instanceof Error ? reason.message : "分析未完成，请查看运行列表后再重试。"); }
    finally { setBusy(false); setAnalyzing(false); }
  }

  return (
    <ProductChrome
      eyebrow="观察清单"
      title="我的观察清单"
      subtitle="记录尚未持有但想研究的标的。添加后可选择组合上下文发起分析，不会创建持仓。"
    >
      {analysisTarget ? <AnalysisStartDialog label={`${analysisTarget.symbol} ${analysisTarget.name}`} onCancel={() => setAnalysisTarget(null)} onConfirm={(portfolioId) => void analyze(analysisTarget, portfolioId)} /> : null}
      <div className="action-feedback">
      <StatusBanner kind="error" text={error} />
      <StatusBanner kind="ok" text={message} />
      <StatusBanner kind="info" text={analyzing ? "正在调用投资团队分析，可能需要 1–2 分钟。请保留页面；完成后打开报告。" : loading ? "正在读取观察清单…" : null} />
      </div>
      {error ? <button type="button" className="btn" disabled={busy || loading} onClick={() => { setError(null); setLoading(true); void load().catch(() => setError("无法读取观察清单，请检查本地服务后重试。")).finally(() => setLoading(false)); }}>重新读取清单</button> : null}

      <div className="stat-row">
        <article className="stat-card">
          <span>观察数量</span>
          <strong>{items.length}</strong>
          <small>可随时增删</small>
        </article>
        <article className="stat-card">
          <span>研究状态</span>
          <strong>按实显示</strong>
          <small>不编造生命周期 / 逻辑状态</small>
        </article>
        <article className="stat-card warn">
          <span>下一步</span>
          <strong>发起研究</strong>
          <small>在下方清单点击「立即分析」</small>
        </article>
      </div>

      <div className="two-col">
        <Panel title="加入观察" description="可搜索目录选标的，或手动填。五位代码识别为港股。">
          <InstrumentSearchBox
            onSelect={(hit) => {
              setMarket(hit.market);
              setSymbol(hit.symbol);
              setName(hit.name);
              setAssetType(hit.asset_type);
              setCurrency(hit.currency);
              setSector(hit.sector);
            }}
          />
          <form className="form-grid" onSubmit={addItem}>
            <label className="field">
              <span>市场</span>
              <select value={market} onChange={(e) => setMarket(e.target.value)}>
                <option value="">自动识别</option>
                <option value="SSE">上海 SSE</option>
                <option value="SZSE">深圳 SZSE</option>
                <option value="HKEX">香港 HKEX</option>
              </select>
            </label>
            <label className="field">
              <span>代码</span>
              <input
                value={symbol}
                placeholder="000001"
                onChange={(e) => setSymbol(e.target.value)}
                required
              />
            </label>
            <label className="field">
              <span>名称</span>
              <input
                value={name}
                placeholder="平安银行"
                onChange={(e) => setName(e.target.value)}
                required
              />
            </label>
            <button type="submit" className="btn primary" disabled={busy}>
              加入清单
            </button>
          </form>
        </Panel>

        <Panel title="说明" tone="muted">
          <ul className="tip-list">
            <li>重复加入同一代码不会写两遍。</li>
            <li>「未提供」表示没有可读数据，不等于零，也不一定表示从未分析。</li>
            <li>分析需要一个组合上下文，可以是空持仓组合；标的不会因此被买入。</li>
            <li>报告仅作研究，不产生订单。</li>
          </ul>
        </Panel>
      </div>

      <Panel title="清单">
        {items.length === 0 ? (
          <EmptyState title={loading ? "正在读取清单" : error ? "清单暂不可读取" : "清单是空的"} hint="可用搜索选中标的，或填写代码与名称后点击「加入清单」。" />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>代码</th>
                <th>名称</th>
                <th>生命周期</th>
                <th>投资逻辑</th>
                <th>数据新鲜度</th>
                <th>下一步盯什么</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.watchlist_item_id}>
                  <td>
                    <strong>{item.symbol}</strong>
                    <div className="muted">{item.market}</div>
                  </td>
                  <td>{item.name}</td>
                  <td>
                    <span className="pill missing">{item.lifecycle_state ?? "未提供"}</span>
                  </td>
                  <td>
                    <span className="pill missing">{item.thesis_state ?? "未提供"}</span>
                  </td>
                  <td>
                    <span
                      className={`pill ${
                        item.data_freshness_status === "STALE" ||
                        item.data_freshness_status === "EXPIRED" ||
                        item.data_freshness_status === "NOT_YET_AVAILABLE"
                          ? "warn"
                          : "missing"
                      }`}
                    >
                      {!item.data_freshness_as_of && !item.data_freshness_status
                        ? "未提供"
                        : item.data_freshness_status
                          ? `${item.data_freshness_status}${
                              item.data_freshness_as_of
                                ? ` · ${item.data_freshness_as_of}`
                                : ""
                            }`
                          : item.data_freshness_as_of}
                    </span>
                  </td>
                  <td>
                    <span className="pill missing">
                      {item.next_monitoring_condition ?? "未提供"}
                    </span>
                  </td>
                  <td>
                    <button type="button" className="btn" disabled={busy} onClick={() => setAnalysisTarget(item)}>{analyzing ? "分析中…" : "立即分析"}</button>
                    <button
                      type="button"
                      className="btn danger ghost"
                      disabled={busy}
                      onClick={() => void removeItem(item)}
                    >
                      移除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </ProductChrome>
  );
}
