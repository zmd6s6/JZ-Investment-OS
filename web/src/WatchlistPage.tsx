import { FormEvent, useCallback, useEffect, useState } from "react";

import { EmptyState, Panel, ProductChrome, StatusBanner } from "./ProductChrome";
import { InstrumentSearchBox } from "./InstrumentSearchBox";
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

  const load = useCallback(async () => {
    const response = await fetch("/api/v1/watchlist");
    if (!response.ok) throw new Error("无法加载观察清单");
    setItems((await response.json()) as WatchlistItem[]);
  }, []);

  useEffect(() => {
    void load().catch((reason: unknown) =>
      setError(reason instanceof Error ? reason.message : "加载失败"),
    );
  }, [load]);

  async function addItem(event: FormEvent) {
    event.preventDefault();
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

  return (
    <ProductChrome
      eyebrow="观察清单"
      title="我在盯的票"
      subtitle="只记代码和名称。研究状态有数据才显示，没有就是「未提供」。"
    >
      <StatusBanner kind="error" text={error} />
      <StatusBanner kind="ok" text={message} />

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
          <strong>等分析</strong>
          <small>分析功能接上后自动填充</small>
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
            <li>「未提供」= 还没分析，不是零。</li>
            <li>这里不产生任何交易建议。</li>
          </ul>
        </Panel>
      </div>

      <Panel title="清单">
        {items.length === 0 ? (
          <EmptyState title="清单是空的" hint="在上面加一只票试试。" />
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
                    <span className="pill missing">
                      {!item.data_freshness_as_of
                        ? "未提供"
                        : item.data_freshness_status === "STALE" ||
                            item.data_freshness_status === "EXPIRED"
                          ? `${item.data_freshness_status} · ${item.data_freshness_as_of}`
                          : item.data_freshness_as_of}
                    </span>
                  </td>
                  <td>
                    <span className="pill missing">
                      {item.next_monitoring_condition ?? "未提供"}
                    </span>
                  </td>
                  <td>
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
