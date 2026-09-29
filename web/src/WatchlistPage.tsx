import { FormEvent, useCallback, useEffect, useState } from "react";

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
  next_monitoring_condition: string | null;
};

const emptyForm = {
  market: "SSE",
  symbol: "",
  name: "",
  asset_type: "EQUITY",
  currency: "CNY",
  sector: "",
};

export function WatchlistPage() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

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
    setError(null);
    setMessage(null);
    const response = await fetch("/api/v1/watchlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    if (!response.ok) {
      setError("加入观察清单失败");
      return;
    }
    setMessage("已加入观察清单（缺失状态显示为未提供）");
    setForm(emptyForm);
    await load();
  }

  async function removeItem(item: WatchlistItem) {
    setError(null);
    const response = await fetch(
      `/api/v1/watchlist/${encodeURIComponent(item.market)}/${encodeURIComponent(item.symbol)}`,
      { method: "DELETE" },
    );
    if (!response.ok) {
      setError("移除失败");
      return;
    }
    setMessage("已移除");
    await load();
  }

  return (
    <main className="product-shell">
      <header className="product-header">
        <div>
          <p className="eyebrow">PRODUCT-05 · 观察清单</p>
          <h1>Watchlist</h1>
        </div>
        <a className="back-link" href="/">
          返回向导
        </a>
      </header>
      <p className="legacy-warning">
        仅维护观察标的。lifecycle / Thesis / 数据新鲜度 / 下一监控条件在数据可得前显示“未提供”，绝不伪造。
      </p>
      {error ? <p className="error-text">{error}</p> : null}
      {message ? <p className="ok-text">{message}</p> : null}

      <section className="legacy-page">
        <h2>添加标的</h2>
        <form onSubmit={addItem} className="stack-form">
          <label>
            market
            <input
              value={form.market}
              onChange={(e) => setForm({ ...form, market: e.target.value })}
            />
          </label>
          <label>
            symbol
            <input
              value={form.symbol}
              onChange={(e) => setForm({ ...form, symbol: e.target.value })}
            />
          </label>
          <label>
            name
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </label>
          <label>
            currency
            <input
              value={form.currency}
              onChange={(e) => setForm({ ...form, currency: e.target.value })}
            />
          </label>
          <button type="submit">加入</button>
        </form>
      </section>

      <section className="legacy-page">
        <h2>清单</h2>
        {items.length === 0 ? (
          <p>未提供观察标的</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>symbol</th>
                <th>name</th>
                <th>lifecycle</th>
                <th>thesis</th>
                <th>freshness</th>
                <th>next monitoring</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.watchlist_item_id}>
                  <td>{item.symbol}</td>
                  <td>{item.name}</td>
                  <td>{item.lifecycle_state ?? "未提供"}</td>
                  <td>{item.thesis_state ?? "未提供"}</td>
                  <td>{item.data_freshness_as_of ?? "未提供"}</td>
                  <td>{item.next_monitoring_condition ?? "未提供"}</td>
                  <td>
                    <button type="button" onClick={() => void removeItem(item)}>
                      移除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}
