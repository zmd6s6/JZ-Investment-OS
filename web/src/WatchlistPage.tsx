import { FormEvent, useCallback, useEffect, useState } from "react";

import { EmptyState, Field, Panel, ProductChrome, StatusBanner } from "./ProductChrome";

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
      const response = await fetch("/api/v1/watchlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!response.ok) throw new Error("加入观察清单失败");
      setMessage("已加入观察清单");
      setForm(emptyForm);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "加入观察清单失败");
    } finally {
      setBusy(false);
    }
  }

  async function removeItem(item: WatchlistItem) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const response = await fetch(
        `/api/v1/watchlist/${encodeURIComponent(item.market)}/${encodeURIComponent(item.symbol)}`,
        { method: "DELETE" },
      );
      if (!response.ok) throw new Error("移除失败");
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
      eyebrow="PRODUCT-05 · 观察清单"
      title="Watchlist"
      subtitle="只维护盯什么票。状态字段有数据才显示，没有就写「未提供」，绝不伪造。"
    >
      <StatusBanner kind="error" text={error} />
      <StatusBanner kind="ok" text={message} />

      <div className="stat-row">
        <article className="stat-card">
          <span>观察标的</span>
          <strong>{items.length}</strong>
          <small>只增删，不改投资结论</small>
        </article>
        <article className="stat-card">
          <span>数据完整性</span>
          <strong>诚实显示</strong>
          <small>缺 lifecycle / Thesis / 新鲜度时标未提供</small>
        </article>
        <article className="stat-card warn">
          <span>下一步</span>
          <strong>P6 分析</strong>
          <small>分析链路接上后才填充研究状态</small>
        </article>
      </div>

      <div className="two-col">
        <Panel title="添加标的" description="录入身份信息，系统会规范化市场与代码。">
          <form className="form-grid" onSubmit={addItem}>
            <Field
              label="market"
              value={form.market}
              onChange={(v) => setForm({ ...form, market: v })}
            />
            <Field
              label="symbol"
              value={form.symbol}
              onChange={(v) => setForm({ ...form, symbol: v })}
              placeholder="000001"
            />
            <Field
              label="name"
              value={form.name}
              onChange={(v) => setForm({ ...form, name: v })}
              placeholder="平安银行"
            />
            <Field
              label="currency"
              value={form.currency}
              onChange={(v) => setForm({ ...form, currency: v })}
            />
            <Field
              label="sector"
              value={form.sector}
              onChange={(v) => setForm({ ...form, sector: v })}
            />
            <button type="submit" className="btn primary" disabled={busy}>
              加入
            </button>
          </form>
        </Panel>

        <Panel title="使用提示" tone="muted">
          <ul className="tip-list">
            <li>加入后可在下表移除；重复添加同一代码是幂等的。</li>
            <li>lifecycle / Thesis / 新鲜度 / 监控条件来自后续分析链路。</li>
            <li>本页不产生交易建议，也不连接券商。</li>
          </ul>
        </Panel>
      </div>

      <Panel title="清单" description="空白字段表示系统尚未评估，不是零。">
        {items.length === 0 ? (
          <EmptyState title="清单为空" hint="在上方添加第一只观察标的。" />
        ) : (
          <table className="data-table">
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
                  <td>
                    <strong>{item.symbol}</strong>
                    <div className="muted">{item.market}</div>
                  </td>
                  <td>
                    {item.name}
                    <div className="muted">{item.currency}</div>
                  </td>
                  <td>
                    <span className="pill missing">{item.lifecycle_state ?? "未提供"}</span>
                  </td>
                  <td>
                    <span className="pill missing">{item.thesis_state ?? "未提供"}</span>
                  </td>
                  <td>
                    <span className="pill missing">{item.data_freshness_as_of ?? "未提供"}</span>
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
