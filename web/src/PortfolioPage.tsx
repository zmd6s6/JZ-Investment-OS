import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState, Field, Panel, ProductChrome, StatusBanner } from "./ProductChrome";

type PortfolioPosition = {
  position_id: string;
  instrument_id: string;
  market: string;
  symbol: string;
  name: string;
  asset_type: string;
  currency: string;
  sector: string;
  core_quantity: string;
  tactical_quantity: string;
  average_cost: string;
};

type Portfolio = {
  portfolio_id: string;
  name: string;
  base_currency: string;
  cash_balance: string;
  status: string;
  as_of: string;
  missing_pricing: boolean;
  positions: PortfolioPosition[];
};

type CsvRow = {
  line_number: number;
  status: "VALID" | "INVALID" | "DUPLICATE";
  reason: string | null;
  market?: string | null;
  symbol?: string | null;
  name?: string | null;
  core_quantity?: string | null;
  tactical_quantity?: string | null;
  average_cost?: string | null;
};

type CsvPreview = {
  total_rows: number;
  can_commit: boolean;
  valid: CsvRow[];
  invalid: CsvRow[];
  duplicates: CsvRow[];
};

const emptyManual = {
  market: "SSE",
  symbol: "",
  name: "",
  asset_type: "EQUITY",
  currency: "CNY",
  sector: "",
  core_quantity: "0",
  tactical_quantity: "0",
  average_cost: "0",
};

const csvSample = [
  "market,symbol,name,asset_type,currency,sector,core_quantity,tactical_quantity,average_cost",
  "SSE,600519,贵州茅台,EQUITY,CNY,Consumer,10,2,1600",
].join("\n");

function formatQty(value: string) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString("zh-CN", { maximumFractionDigits: 4 }) : value;
}

export function PortfolioPage() {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [name, setName] = useState("个人组合");
  const [baseCurrency, setBaseCurrency] = useState("CNY");
  const [cashBalance, setCashBalance] = useState("0");
  const [manual, setManual] = useState(emptyManual);
  const [csvText, setCsvText] = useState("");
  const [preview, setPreview] = useState<CsvPreview | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (preferredId?: string) => {
      const response = await fetch("/api/v1/portfolios");
      if (!response.ok) throw new Error("无法加载资产组合");
      const data = (await response.json()) as Portfolio[];
      setPortfolios(data);
      const nextId = preferredId || selectedId;
      if (nextId && data.some((item) => item.portfolio_id === nextId)) {
        setSelectedId(nextId);
      } else if (data.length > 0) {
        setSelectedId(data[0].portfolio_id);
      }
    },
    [selectedId],
  );

  useEffect(() => {
    void load().catch((reason: unknown) =>
      setError(reason instanceof Error ? reason.message : "加载失败"),
    );
  }, [load]);

  const selected = useMemo(
    () => portfolios.find((item) => item.portfolio_id === selectedId) || portfolios[0],
    [portfolios, selectedId],
  );

  async function createPortfolio(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const response = await fetch("/api/v1/portfolios", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          base_currency: baseCurrency,
          cash_balance: cashBalance,
        }),
      });
      if (!response.ok) throw new Error("创建组合失败");
      const created = (await response.json()) as Portfolio;
      setMessage("组合已创建（暂不计算市值）");
      setSelectedId(created.portfolio_id);
      await load(created.portfolio_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建组合失败");
    } finally {
      setBusy(false);
    }
  }

  async function addPosition(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const response = await fetch(`/api/v1/portfolios/${selected.portfolio_id}/positions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(manual),
      });
      if (!response.ok) throw new Error("持仓写入失败");
      setMessage("持仓已记录（Core / Tactical 分开保存）");
      setManual(emptyManual);
      await load(selected.portfolio_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "持仓写入失败");
    } finally {
      setBusy(false);
    }
  }

  async function previewCsv() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/v1/portfolios/${selected.portfolio_id}/csv/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csv_text: csvText }),
      });
      if (!response.ok) throw new Error("CSV 预览失败");
      setPreview((await response.json()) as CsvPreview);
      setMessage("预览完成：确认前不会写入任何持仓");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "CSV 预览失败");
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }

  async function confirmCsv() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/v1/portfolios/${selected.portfolio_id}/csv/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csv_text: csvText }),
      });
      if (!response.ok) throw new Error("CSV 确认失败（存在无效行时不会写入）");
      setMessage("CSV 已导入，请对照下表核对");
      setPreview(null);
      setCsvText("");
      await load(selected.portfolio_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "CSV 确认失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <ProductChrome
      eyebrow="PRODUCT-05 · 资产组合"
      title="Portfolio"
      subtitle="录入持仓、批量导入并核对。本页不计算市值/收益，也不给出买卖建议。"
    >
      <StatusBanner kind="error" text={error} />
      <StatusBanner kind="ok" text={message} />

      <div className="stat-row">
        <article className="stat-card">
          <span>当前组合</span>
          <strong>{selected?.name || "未提供"}</strong>
          <small>
            {selected
              ? `${selected.base_currency} · as-of ${new Date(selected.as_of).toLocaleString("zh-CN")}`
              : "先创建或选择一个组合"}
          </small>
        </article>
        <article className="stat-card">
          <span>现金余额</span>
          <strong>{selected ? formatQty(selected.cash_balance) : "—"}</strong>
          <small>{selected?.base_currency || ""}</small>
        </article>
        <article className="stat-card">
          <span>持仓笔数</span>
          <strong>{selected?.positions.length ?? 0}</strong>
          <small>Core / Tactical 分列</small>
        </article>
        <article className="stat-card warn">
          <span>定价</span>
          <strong>未提供</strong>
          <small>市值与 NAV 归属 P6，此处不伪造</small>
        </article>
      </div>

      <div className="two-col">
        <Panel
          title="切换组合"
          description="创建后自动选中；列表来自真实 API。"
          tone="muted"
        >
          {portfolios.length === 0 ? (
            <EmptyState title="还没有组合" hint="在右侧创建你的第一个组合。" />
          ) : (
            <ul className="select-list">
              {portfolios.map((item) => (
                <li key={item.portfolio_id}>
                  <button
                    type="button"
                    className={item.portfolio_id === selected?.portfolio_id ? "selected" : ""}
                    onClick={() => setSelectedId(item.portfolio_id)}
                  >
                    <strong>{item.name}</strong>
                    <span>
                      {item.base_currency} · {item.positions.length} 笔持仓
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="创建组合" description="名称、基础货币与现金。可先建组合再补持仓。">
          <form className="form-grid" onSubmit={createPortfolio}>
            <Field label="名称" value={name} onChange={setName} />
            <Field
              label="基础货币"
              value={baseCurrency}
              onChange={setBaseCurrency}
              hint="3 位代码，如 CNY / USD / HKD"
            />
            <Field label="现金余额" value={cashBalance} onChange={setCashBalance} />
            <button type="submit" className="btn primary" disabled={busy}>
              创建
            </button>
          </form>
        </Panel>
      </div>

      <Panel
        title="手工录入持仓"
        description="每笔明确市场、代码、数量与成本。核心仓与短线仓分开记账。"
      >
        <form className="form-grid wide" onSubmit={addPosition}>
          <Field
            label="market"
            value={manual.market}
            onChange={(v) => setManual({ ...manual, market: v })}
            hint="SSE / SZSE / HKEX…"
          />
          <Field
            label="symbol"
            value={manual.symbol}
            onChange={(v) => setManual({ ...manual, symbol: v })}
            placeholder="600519"
          />
          <Field
            label="name"
            value={manual.name}
            onChange={(v) => setManual({ ...manual, name: v })}
            placeholder="贵州茅台"
          />
          <Field
            label="currency"
            value={manual.currency}
            onChange={(v) => setManual({ ...manual, currency: v })}
          />
          <Field
            label="sector"
            value={manual.sector}
            onChange={(v) => setManual({ ...manual, sector: v })}
            placeholder="Consumer"
          />
          <Field
            label="core_quantity"
            value={manual.core_quantity}
            onChange={(v) => setManual({ ...manual, core_quantity: v })}
          />
          <Field
            label="tactical_quantity"
            value={manual.tactical_quantity}
            onChange={(v) => setManual({ ...manual, tactical_quantity: v })}
          />
          <Field
            label="average_cost"
            value={manual.average_cost}
            onChange={(v) => setManual({ ...manual, average_cost: v })}
          />
          <button type="submit" className="btn primary" disabled={busy || !selected}>
            记录持仓
          </button>
        </form>
      </Panel>

      <Panel
        title="CSV 导入"
        description="先预览再确认。存在无效行时禁止写入，避免半截导入。"
        actions={
          <button type="button" className="btn ghost" onClick={() => setCsvText(csvSample)}>
            填入示例
          </button>
        }
      >
        <p className="hint-text">
          表头必须包含：
          <code>market,symbol,name,asset_type,currency,sector,core_quantity,tactical_quantity,average_cost</code>
        </p>
        <textarea
          className="csv-input"
          value={csvText}
          onChange={(e) => setCsvText(e.target.value)}
          rows={7}
          aria-label="CSV 内容"
          placeholder={csvSample}
        />
        <div className="btn-row">
          <button type="button" className="btn" onClick={() => void previewCsv()} disabled={busy}>
            预览
          </button>
          <button
            type="button"
            className="btn primary"
            onClick={() => void confirmCsv()}
            disabled={busy || !preview?.can_commit}
          >
            确认导入
          </button>
          {!preview?.can_commit && preview ? (
            <span className="inline-note">存在无效行，确认按钮保持禁用</span>
          ) : null}
        </div>

        {preview ? (
          <div className="preview-block">
            <div className="chip-row">
              <span className="chip">共 {preview.total_rows} 行</span>
              <span className="chip ok">有效 {preview.valid.length}</span>
              <span className="chip bad">无效 {preview.invalid.length}</span>
              <span className="chip warn">重复 {preview.duplicates.length}</span>
              <span className={`chip ${preview.can_commit ? "ok" : "bad"}`}>
                {preview.can_commit ? "可确认导入" : "存在无效行，禁止写入"}
              </span>
            </div>
            <table className="data-table">
              <thead>
                <tr>
                  <th>行</th>
                  <th>状态</th>
                  <th>symbol</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                {[...preview.invalid, ...preview.duplicates, ...preview.valid].map((row) => (
                  <tr key={`${row.line_number}-${row.status}`} className={`row-${row.status.toLowerCase()}`}>
                    <td>{row.line_number}</td>
                    <td>
                      <span className={`pill ${row.status.toLowerCase()}`}>{row.status}</span>
                    </td>
                    <td>{row.symbol || "—"}</td>
                    <td>{row.reason || "ok"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Panel>

      <Panel title="对账视图" description="导入或手工录入后，用这张表核对数量与成本。">
        {!selected || selected.positions.length === 0 ? (
          <EmptyState title="暂无持仓" hint="用上方手工录入或 CSV 导入后，这里会列出结果。" />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>market</th>
                <th>symbol</th>
                <th>name</th>
                <th>Core</th>
                <th>Tactical</th>
                <th>均价</th>
                <th>currency</th>
              </tr>
            </thead>
            <tbody>
              {selected.positions.map((position) => (
                <tr key={position.position_id}>
                  <td>{position.market}</td>
                  <td>
                    <strong>{position.symbol}</strong>
                  </td>
                  <td>{position.name}</td>
                  <td>{formatQty(position.core_quantity)}</td>
                  <td>{formatQty(position.tactical_quantity)}</td>
                  <td>{formatQty(position.average_cost)}</td>
                  <td>{position.currency}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </ProductChrome>
  );
}
