import { FormEvent, useCallback, useEffect, useState } from "react";

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

  const load = useCallback(async (preferredId?: string) => {
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
  }, [selectedId]);

  useEffect(() => {
    void load().catch((reason: unknown) =>
      setError(reason instanceof Error ? reason.message : "加载失败"),
    );
  }, [load]);

  const selected = portfolios.find((item) => item.portfolio_id === selectedId) || portfolios[0];

  async function createPortfolio(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    const response = await fetch("/api/v1/portfolios", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        base_currency: baseCurrency,
        cash_balance: cashBalance,
      }),
    });
    if (!response.ok) {
      setError("创建组合失败");
      return;
    }
    const created = (await response.json()) as Portfolio;
    setMessage("组合已创建（未计算市值）");
    setSelectedId(created.portfolio_id);
    await load(created.portfolio_id);
  }

  async function addPosition(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setError(null);
    setMessage(null);
    const response = await fetch(`/api/v1/portfolios/${selected.portfolio_id}/positions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(manual),
    });
    if (!response.ok) {
      setError("持仓写入失败");
      return;
    }
    setMessage("持仓已记录（Core/Tactical 分开保存）");
    setManual(emptyManual);
    await load();
  }

  async function previewCsv() {
    if (!selected) return;
    setError(null);
    const response = await fetch(`/api/v1/portfolios/${selected.portfolio_id}/csv/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ csv_text: csvText }),
    });
    if (!response.ok) {
      setError("CSV 预览失败");
      setPreview(null);
      return;
    }
    setPreview((await response.json()) as CsvPreview);
  }

  async function confirmCsv() {
    if (!selected) return;
    setError(null);
    const response = await fetch(`/api/v1/portfolios/${selected.portfolio_id}/csv/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ csv_text: csvText }),
    });
    if (!response.ok) {
      setError("CSV 确认失败（存在无效行时不会写入）");
      return;
    }
    setMessage("CSV 已导入；请对照下表核对持仓");
    setPreview(null);
    setCsvText("");
    await load();
  }

  return (
    <main className="product-shell">
      <header className="product-header">
        <div>
          <p className="eyebrow">PRODUCT-05 · 资产组合</p>
          <h1>Portfolio</h1>
        </div>
        <a className="back-link" href="/">
          返回向导
        </a>
      </header>
      <p className="legacy-warning">
        SIMULATION / NO AUTO TRADE。此页不计算市值、收益或建议仓位；数据 as-of
        {selected ? ` ${selected.as_of}` : " 未提供"}。个人持仓不会写入仓库。
      </p>
      {error ? <p className="error-text">{error}</p> : null}
      {message ? <p className="ok-text">{message}</p> : null}

      <section className="legacy-page">
        <h2>创建组合</h2>
        <form onSubmit={createPortfolio} className="stack-form">
          <label>
            名称
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            基础货币
            <input value={baseCurrency} onChange={(e) => setBaseCurrency(e.target.value)} />
          </label>
          <label>
            现金余额
            <input value={cashBalance} onChange={(e) => setCashBalance(e.target.value)} />
          </label>
          <button type="submit">创建</button>
        </form>
      </section>

      <section className="legacy-page">
        <h2>持仓（手工录入）</h2>
        <form onSubmit={addPosition} className="stack-form">
          <label>
            market
            <input
              value={manual.market}
              onChange={(e) => setManual({ ...manual, market: e.target.value })}
            />
          </label>
          <label>
            symbol
            <input
              value={manual.symbol}
              onChange={(e) => setManual({ ...manual, symbol: e.target.value })}
            />
          </label>
          <label>
            name
            <input
              value={manual.name}
              onChange={(e) => setManual({ ...manual, name: e.target.value })}
            />
          </label>
          <label>
            currency
            <input
              value={manual.currency}
              onChange={(e) => setManual({ ...manual, currency: e.target.value })}
            />
          </label>
          <label>
            sector
            <input
              value={manual.sector}
              onChange={(e) => setManual({ ...manual, sector: e.target.value })}
            />
          </label>
          <label>
            core_quantity
            <input
              value={manual.core_quantity}
              onChange={(e) => setManual({ ...manual, core_quantity: e.target.value })}
            />
          </label>
          <label>
            tactical_quantity
            <input
              value={manual.tactical_quantity}
              onChange={(e) => setManual({ ...manual, tactical_quantity: e.target.value })}
            />
          </label>
          <label>
            average_cost
            <input
              value={manual.average_cost}
              onChange={(e) => setManual({ ...manual, average_cost: e.target.value })}
            />
          </label>
          <button type="submit">记录持仓</button>
        </form>
      </section>

      <section className="legacy-page">
        <h2>CSV 导入（先预览，后确认）</h2>
        <p>
          表头必须包含：market,symbol,name,asset_type,currency,sector,core_quantity,tactical_quantity,average_cost
        </p>
        <textarea
          value={csvText}
          onChange={(e) => setCsvText(e.target.value)}
          rows={6}
          aria-label="CSV 内容"
        />
        <div className="legacy-tabs">
          <button type="button" onClick={() => void previewCsv()}>
            预览
          </button>
          <button type="button" onClick={() => void confirmCsv()} disabled={!preview?.can_commit}>
            确认导入
          </button>
        </div>
        {preview ? (
          <div>
            <p>
              共 {preview.total_rows} 行 · 有效 {preview.valid.length} · 无效 {preview.invalid.length} ·
              重复 {preview.duplicates.length} ·{" "}
              {preview.can_commit ? "可确认导入" : "存在无效行，禁止写入"}
            </p>
            <ul>
              {[...preview.invalid, ...preview.duplicates, ...preview.valid].map((row) => (
                <li key={`${row.line_number}-${row.status}`}>
                  行 {row.line_number} · {row.status} · {row.symbol || "-"} ·{" "}
                  {row.reason || "ok"}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>

      <section className="legacy-page">
        <h2>对账视图</h2>
        {!selected ? (
          <p>未提供组合</p>
        ) : (
          <div>
            <p>
              {selected.name} · {selected.base_currency} · 现金 {selected.cash_balance} ·{" "}
              {selected.missing_pricing ? "未提供市值/NAV" : ""}
            </p>
            <table>
              <thead>
                <tr>
                  <th>symbol</th>
                  <th>name</th>
                  <th>core</th>
                  <th>tactical</th>
                  <th>avg cost</th>
                </tr>
              </thead>
              <tbody>
                {selected.positions.map((position) => (
                  <tr key={position.position_id}>
                    <td>{position.symbol}</td>
                    <td>{position.name}</td>
                    <td>{position.core_quantity}</td>
                    <td>{position.tactical_quantity}</td>
                    <td>{position.average_cost}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
