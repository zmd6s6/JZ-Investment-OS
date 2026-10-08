import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState, Panel, ProductChrome, StatusBanner } from "./ProductChrome";
import { InstrumentSearchBox } from "./InstrumentSearchBox";
import { apiFetch, readApiError } from "./writeApi";

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
  status: "VALID" | "INVALID" | "DUPLICATE" | "CONFLICT";
  reason: string | null;
  market?: string | null;
  symbol?: string | null;
  name?: string | null;
  core_quantity?: string | null;
  tactical_quantity?: string | null;
  average_cost?: string | null;
  existing_core_quantity?: string | null;
  existing_tactical_quantity?: string | null;
  existing_average_cost?: string | null;
};

type CsvPreview = {
  total_rows: number;
  can_commit: boolean;
  requires_conflict_policy: boolean;
  content_hash: string;
  valid: CsvRow[];
  invalid: CsvRow[];
  duplicates: CsvRow[];
  conflicts: CsvRow[];
};

function num(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return n.toLocaleString("zh-CN", { maximumFractionDigits: 4 });
}

function guessMarket(symbol: string) {
  const s = symbol.trim();
  // 5-digit codes are HKEX; must be checked before A-share prefix rules
  if (/^\d{5}$/.test(s)) return "HKEX";
  if (/^[69]/.test(s)) return "SSE";
  if (/^[03]/.test(s)) return "SZSE";
  return "";
}

const emptyManual = {
  market: "",
  symbol: "",
  name: "",
  core_quantity: "0",
  tactical_quantity: "0",
  average_cost: "0",
  core_average_cost: "",
  tactical_average_cost: "",
  core_reason: "",
  tactical_reason: "",
  currency: "CNY",
  sector: "",
};

const csvSample = [
  "market,symbol,name,asset_type,currency,sector,core_quantity,tactical_quantity,average_cost",
  "SSE,600519,贵州茅台,EQUITY,CNY,Consumer,10,2,1600",
].join("\n");

export function PortfolioPage() {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [name, setName] = useState("我的组合");
  const [baseCurrency, setBaseCurrency] = useState("CNY");
  const [cashBalance, setCashBalance] = useState("0");
  const [manual, setManual] = useState(emptyManual);
  const [showMore, setShowMore] = useState(false);
  const [csvText, setCsvText] = useState("");
  const [preview, setPreview] = useState<CsvPreview | null>(null);
  const [conflictPolicy, setConflictPolicy] = useState<"SKIP" | "REPLACE" | "UPDATE" | "">("");
  const [importHistory, setImportHistory] = useState<
    {
      audit_id: string;
      conflict_policy: string;
      created_at: string;
      applied: {
        line_number: number;
        market: string;
        symbol: string;
        action: string;
      }[];
    }[]
  >([]);
  const [importReport, setImportReport] = useState<null | {
    imported_count: number;
    skipped_count: number;
    audit_id: string;
    applied: {
      line_number: number;
      market: string;
      symbol: string;
      action: string;
      before: Record<string, string> | null;
      after: Record<string, string>;
    }[];
  }>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (preferredId?: string) => {
      const response = await apiFetch("/api/v1/portfolios");
      if (!response.ok) throw new Error(await readApiError(response));
      const data = (await response.json()) as Portfolio[];
      setPortfolios(data);
      const nextId = preferredId || selectedId;
      if (nextId && data.some((item) => item.portfolio_id === nextId)) {
        setSelectedId(nextId);
      } else if (data.length > 0) {
        setSelectedId(data[0].portfolio_id);
      }
      const historyId =
        nextId && data.some((item) => item.portfolio_id === nextId)
          ? nextId
          : data[0]?.portfolio_id;
      if (historyId) {
        const historyResponse = await apiFetch(
          `/api/v1/portfolios/${historyId}/import-audits?limit=10`,
        );
        if (historyResponse.ok) {
          setImportHistory(
            (await historyResponse.json()) as typeof importHistory,
          );
        }
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
      const response = await apiFetch("/api/v1/portfolios", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          base_currency: baseCurrency,
          cash_balance: cashBalance,
        }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const created = (await response.json()) as Portfolio;
      setMessage("组合已创建");
      setSelectedId(created.portfolio_id);
      setManual((prev) => ({ ...prev, currency: created.base_currency }));
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
      const market = manual.market || guessMarket(manual.symbol);
      if (!market) throw new Error("请填写市场，或输入标准 A 股/港股代码自动识别");
      const response = await apiFetch(`/api/v1/portfolios/${selected.portfolio_id}/positions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          market,
          symbol: manual.symbol,
          name: manual.name,
          asset_type: "EQUITY",
          currency: manual.currency || selected.base_currency,
          sector: manual.sector,
          core_quantity: manual.core_quantity || "0",
          tactical_quantity: manual.tactical_quantity || "0",
          average_cost: manual.average_cost || "0",
          core_average_cost: manual.core_average_cost || null,
          tactical_average_cost: manual.tactical_average_cost || null,
          core_reason: manual.core_reason,
          tactical_reason: manual.tactical_reason,
          operation: "MANUAL",
        }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      setMessage("持仓已保存");
      setManual((prev) => ({
        ...emptyManual,
        currency: prev.currency,
      }));
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
      const response = await apiFetch(`/api/v1/portfolios/${selected.portfolio_id}/csv/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csv_text: csvText }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      setPreview((await response.json()) as CsvPreview);
      setMessage("预览完成。与现有持仓冲突时，必须显式选择处理方式后才能导入。");
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
      const response = await apiFetch(`/api/v1/portfolios/${selected.portfolio_id}/csv/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          csv_text: csvText,
          conflict_policy: preview?.requires_conflict_policy ? conflictPolicy : undefined,
          expected_preview_hash: preview?.content_hash,
        }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const result = (await response.json()) as NonNullable<typeof importReport>;
      setImportReport(result);
      setMessage(
        `已导入 ${result.imported_count} 笔，跳过 ${result.skipped_count} 笔。下方可查看逐行对账。`,
      );
      setPreview(null);
      setCsvText("");
      await load(selected.portfolio_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "导入失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <ProductChrome
      eyebrow="资产组合"
      title="我的持仓"
      subtitle="录入或导入持仓。不计算市值，不给买卖建议。"
    >
      <StatusBanner kind="error" text={error} />
      <StatusBanner kind="ok" text={message} />

      <div className="stat-row">
        <article className="stat-card">
          <span>当前组合</span>
          <strong>{selected?.name || "未选择"}</strong>
          <small>
            {selected
              ? `${selected.base_currency} · 更新于 ${new Date(selected.as_of).toLocaleString("zh-CN")}`
              : "先创建一个组合"}
          </small>
        </article>
        <article className="stat-card">
          <span>现金</span>
          <strong>{selected ? num(selected.cash_balance) : "—"}</strong>
          <small>{selected?.base_currency || ""}</small>
        </article>
        <article className="stat-card">
          <span>持仓</span>
          <strong>{selected?.positions.length ?? 0} 笔</strong>
          <small>核心仓 / 短线仓</small>
        </article>
        <article className="stat-card warn">
          <span>市值</span>
          <strong>未提供</strong>
          <small>后续版本再算</small>
        </article>
      </div>

      <div className="two-col">
        <Panel title="选择组合" tone="muted">
          {portfolios.length === 0 ? (
            <EmptyState title="还没有组合" hint="在右边创建。" />
          ) : (
            <ul className="select-list">
              {portfolios.map((item) => (
                <li key={item.portfolio_id}>
                  <button
                    type="button"
                    className={item.portfolio_id === selected?.portfolio_id ? "selected" : ""}
                    onClick={() => {
                      setSelectedId(item.portfolio_id);
                      setManual((prev) => ({ ...prev, currency: item.base_currency }));
                    }}
                  >
                    <strong>{item.name}</strong>
                    <span>
                      {item.base_currency} · {item.positions.length} 笔
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="新建组合" description="只需名称和货币。">
          <form className="form-grid" onSubmit={createPortfolio}>
            <label className="field">
              <span>组合名称</span>
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="field">
              <span>记账货币</span>
              <select value={baseCurrency} onChange={(e) => setBaseCurrency(e.target.value)}>
                <option value="CNY">人民币 CNY</option>
                <option value="USD">美元 USD</option>
                <option value="HKD">港币 HKD</option>
              </select>
            </label>
            <label className="field">
              <span>现金（可选）</span>
              <input
                value={cashBalance}
                onChange={(e) => setCashBalance(e.target.value)}
                inputMode="decimal"
              />
            </label>
            <button type="submit" className="btn primary" disabled={busy}>
              创建组合
            </button>
          </form>
          {selected ? (
            <form
              className="form-grid more-grid"
              onSubmit={async (event) => {
                event.preventDefault();
                setBusy(true);
                setError(null);
                setMessage(null);
                try {
                  const response = await apiFetch(
                    `/api/v1/portfolios/${selected.portfolio_id}/cash`,
                    {
                      method: "PUT",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ cash_balance: cashBalance }),
                    },
                  );
                  if (!response.ok) throw new Error(await readApiError(response));
                  setMessage("现金已更新");
                  await load(selected.portfolio_id);
                } catch (reason) {
                  setError(reason instanceof Error ? reason.message : "现金更新失败");
                } finally {
                  setBusy(false);
                }
              }}
            >
              <label className="field">
                <span>更新现金（当前组合）</span>
                <input
                  value={cashBalance}
                  inputMode="decimal"
                  onChange={(e) => setCashBalance(e.target.value)}
                />
              </label>
              <button type="submit" className="btn" disabled={busy}>
                更新现金
              </button>
            </form>
          ) : null}
        </Panel>
      </div>

      <Panel
        title="记一笔持仓"
        description="可用目录搜索选标的；也可手填。市场可自动识别（五位代码为港股）。"
      >
        <InstrumentSearchBox
          onSelect={(hit) => {
            setManual((prev) => ({
              ...prev,
              market: hit.market,
              symbol: hit.symbol,
              name: hit.name,
              currency: hit.currency,
              sector: hit.sector,
            }));
            setMessage(`已选择 ${hit.market} ${hit.symbol}`);
          }}
        />
        <form className="form-grid" onSubmit={addPosition}>
          <label className="field">
            <span>代码</span>
            <input
              value={manual.symbol}
              placeholder="600519"
              onChange={(e) => {
                const symbol = e.target.value;
                setManual((prev) => ({
                  ...prev,
                  symbol,
                  market: prev.market || guessMarket(symbol),
                }));
              }}
            />
          </label>
          <label className="field">
            <span>名称</span>
            <input
              value={manual.name}
              placeholder="贵州茅台"
              onChange={(e) => setManual({ ...manual, name: e.target.value })}
            />
          </label>
          <label className="field">
            <span title="长期持有的底仓">长期仓数量</span>
            <input
              value={manual.core_quantity}
              inputMode="decimal"
              onChange={(e) => setManual({ ...manual, core_quantity: e.target.value })}
            />
          </label>
          <label className="field">
            <span title="可灵活进出的机动仓">机动仓数量</span>
            <input
              value={manual.tactical_quantity}
              inputMode="decimal"
              onChange={(e) => setManual({ ...manual, tactical_quantity: e.target.value })}
            />
          </label>
          <label className="field">
            <span>买入均价</span>
            <input
              value={manual.average_cost}
              inputMode="decimal"
              onChange={(e) => setManual({ ...manual, average_cost: e.target.value })}
            />
          </label>
          <label className="field">
            <span>长期仓均价</span>
            <input
              value={manual.core_average_cost}
              placeholder="默认同买入均价"
              inputMode="decimal"
              onChange={(e) => setManual({ ...manual, core_average_cost: e.target.value })}
            />
          </label>
          <label className="field">
            <span>机动仓均价</span>
            <input
              value={manual.tactical_average_cost}
              placeholder="默认同买入均价"
              inputMode="decimal"
              onChange={(e) => setManual({ ...manual, tactical_average_cost: e.target.value })}
            />
          </label>
          <label className="field">
            <span>长期仓理由</span>
            <input
              value={manual.core_reason}
              placeholder="例如：底仓、股息"
              onChange={(e) => setManual({ ...manual, core_reason: e.target.value })}
            />
          </label>
          <label className="field">
            <span>机动仓理由</span>
            <input
              value={manual.tactical_reason}
              placeholder="例如：波段、事件"
              onChange={(e) => setManual({ ...manual, tactical_reason: e.target.value })}
            />
          </label>
          <button type="submit" className="btn primary" disabled={busy || !selected}>
            保存持仓
          </button>
        </form>

        <button
          type="button"
          className="btn ghost more-toggle"
          onClick={() => setShowMore((v) => !v)}
        >
          {showMore ? "收起更多选项" : "更多选项（市场 / 行业）"}
        </button>

        {showMore ? (
          <div className="form-grid more-grid">
            <label className="field">
              <span>市场</span>
              <select
                value={manual.market}
                onChange={(e) => setManual({ ...manual, market: e.target.value })}
              >
                <option value="">自动识别</option>
                <option value="SSE">上海 SSE</option>
                <option value="SZSE">深圳 SZSE</option>
                <option value="HKEX">香港 HKEX</option>
              </select>
            </label>
            <label className="field">
              <span>行业（可选）</span>
              <input
                value={manual.sector}
                placeholder="消费 / 金融…"
                onChange={(e) => setManual({ ...manual, sector: e.target.value })}
              />
            </label>
            <label className="field">
              <span>币种</span>
              <select
                value={manual.currency}
                onChange={(e) => setManual({ ...manual, currency: e.target.value })}
              >
                <option value="CNY">人民币</option>
                <option value="USD">美元</option>
                <option value="HKD">港币</option>
              </select>
            </label>
          </div>
        ) : null}
      </Panel>

      <Panel
        title="批量导入 CSV"
        description="先预览、再确认。有错行会拦住，不会导一半。"
        actions={
          <button type="button" className="btn ghost" onClick={() => setCsvText(csvSample)}>
            填入示例
          </button>
        }
      >
        <p className="hint-text">
          第一行须为表头：市场、代码、名称、类型、币种、行业、核心仓、短线仓、均价（英文字段名见示例）。
        </p>
        <textarea
          className="csv-input"
          value={csvText}
          onChange={(e) => {
            setCsvText(e.target.value);
            setPreview(null);
            setMessage(null);
          }}
          rows={6}
          aria-label="CSV 内容"
          placeholder="粘贴 CSV 文本…"
        />
        <div className="btn-row">
          <button type="button" className="btn" onClick={() => void previewCsv()} disabled={busy}>
            预览
          </button>
          <button
            type="button"
            className="btn primary"
            onClick={() => void confirmCsv()}
            disabled={
              busy ||
              !preview?.can_commit ||
              (Boolean(preview?.requires_conflict_policy) && conflictPolicy === "")
            }
          >
            确认导入
          </button>
          {preview?.requires_conflict_policy && conflictPolicy === "" ? (
            <span className="inline-note">请先选择冲突处理方式</span>
          ) : null}
          {preview && !preview.can_commit ? (
            <span className="inline-note">有错误行，暂不能导入</span>
          ) : null}
        </div>

        {preview ? (
          <div className="preview-block">
            <div className="chip-row">
              <span className="chip">共 {preview.total_rows} 行</span>
              <span className="chip ok">有效 {preview.valid.length}</span>
              <span className="chip bad">无效 {preview.invalid.length}</span>
              <span className="chip warn">重复 {preview.duplicates.length}</span>
              <span className="chip warn">与现有持仓冲突 {preview.conflicts.length}</span>
              <span className={`chip ${preview.can_commit ? "ok" : "bad"}`}>
                {preview.can_commit ? "可以导入" : "存在无效行，禁止写入"}
              </span>
            </div>

            {preview.requires_conflict_policy ? (
              <div className="conflict-policy">
                <strong>冲突处理方式（必须选择后才能导入）</strong>
                <label>
                  <input
                    type="radio"
                    name="conflictPolicy"
                    checked={conflictPolicy === ""}
                    onChange={() => setConflictPolicy("")}
                  />
                  请选择…
                </label>
                <label>
                  <input
                    type="radio"
                    name="conflictPolicy"
                    checked={conflictPolicy === "SKIP"}
                    onChange={() => setConflictPolicy("SKIP")}
                  />
                  跳过：保留原持仓，忽略 CSV 中的同代码行
                </label>
                <label>
                  <input
                    type="radio"
                    name="conflictPolicy"
                    checked={conflictPolicy === "REPLACE"}
                    onChange={() => setConflictPolicy("REPLACE")}
                  />
                  替换：用 CSV 数量与均价覆盖原持仓
                </label>
                <label>
                  <input
                    type="radio"
                    name="conflictPolicy"
                    checked={conflictPolicy === "UPDATE"}
                    onChange={() => setConflictPolicy("UPDATE")}
                  />
                  累加：数量相加，均价采用 CSV 均价
                </label>
              </div>
            ) : null}

            <table className="data-table">
              <thead>
                <tr>
                  <th>行号</th>
                  <th>结果</th>
                  <th>代码</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                {[...preview.invalid, ...preview.duplicates, ...preview.conflicts, ...preview.valid].map(
                  (row) => (
                    <tr key={`${row.line_number}-${row.status}`}>
                      <td>{row.line_number}</td>
                      <td>
                        <span
                          className={`pill ${
                            row.status === "VALID"
                              ? "valid"
                              : row.status === "INVALID"
                                ? "invalid"
                                : "warn"
                          }`}
                        >
                          {row.status === "VALID"
                            ? "有效"
                            : row.status === "INVALID"
                              ? "无效"
                              : row.status === "CONFLICT"
                                ? "冲突"
                                : "重复"}
                        </span>
                      </td>
                      <td>{row.symbol || "—"}</td>
                      <td>
                        {row.reason || "可以导入"}
                        {row.status === "CONFLICT" && row.existing_core_quantity ? (
                          <div className="muted">
                            现有：长期 {row.existing_core_quantity} / 机动{" "}
                            {row.existing_tactical_quantity} / 均价 {row.existing_average_cost}
                          </div>
                        ) : null}
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
        ) : null}
      </Panel>

      {importReport ? (
        <Panel
          title="导入对账记录"
          description={`审计编号 ${importReport.audit_id} · 同一 CSV 与策略重复确认会被拒绝`}
        >
          <div className="chip-row">
            <span className="chip ok">写入 {importReport.imported_count}</span>
            <span className="chip">跳过 {importReport.skipped_count}</span>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>行</th>
                <th>代码</th>
                <th>动作</th>
                <th>变更前</th>
                <th>变更后</th>
              </tr>
            </thead>
            <tbody>
              {importReport.applied.map((row) => (
                <tr key={`${row.line_number}-${row.symbol}-${row.action}`}>
                  <td>{row.line_number}</td>
                  <td>
                    {row.market} {row.symbol}
                  </td>
                  <td>
                    <span className="pill valid">{row.action}</span>
                  </td>
                  <td>
                    {row.before
                      ? `长期 ${row.before.core_quantity} / 机动 ${row.before.tactical_quantity} / 均价 ${row.before.average_cost}`
                      : "—"}
                  </td>
                  <td>
                    长期 {row.after.core_quantity} / 机动 {row.after.tactical_quantity} / 均价{" "}
                    {row.after.average_cost}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      ) : null}

      {importHistory.length > 0 ? (
        <Panel title="导入历史" description="从已保存审计记录读取，刷新后仍在。">
          <ul className="tip-list">
            {importHistory.map((item) => (
              <li key={item.audit_id}>
                {new Date(item.created_at).toLocaleString("zh-CN")} · 策略{" "}
                {item.conflict_policy} · {item.applied.length} 行 · 审计{" "}
                {item.audit_id.slice(0, 8)}…
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}

      <Panel title="持仓一览" description="点击行可载入编辑。导入或录入后在这里核对。">
        {!selected || selected.positions.length === 0 ? (
          <EmptyState title="暂无持仓" hint="用上面的方式录入后，这里会显示。" />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>代码</th>
                <th>名称</th>
                <th>市场</th>
                <th title="长期持有的底仓">长期仓</th>
                <th title="可灵活进出的机动仓">机动仓</th>
                <th>均价</th>
                <th>币种</th>
              </tr>
            </thead>
            <tbody>
              {selected.positions.map((position) => (
                <tr
                  key={position.position_id}
                  className="clickable-row"
                  onClick={() => {
                    setManual({
                      market: position.market,
                      symbol: position.symbol,
                      name: position.name,
                      core_quantity: String(position.core_quantity),
                      tactical_quantity: String(position.tactical_quantity),
                      average_cost: String(position.average_cost),
                      core_average_cost: String(
                        (position as { core_average_cost?: string }).core_average_cost ??
                          position.average_cost,
                      ),
                      tactical_average_cost: String(
                        (position as { tactical_average_cost?: string }).tactical_average_cost ??
                          position.average_cost,
                      ),
                      core_reason: (position as { core_reason?: string }).core_reason ?? "",
                      tactical_reason: (position as { tactical_reason?: string }).tactical_reason ?? "",
                      currency: position.currency,
                      sector: position.sector,
                    });
                    setMessage(`已载入 ${position.symbol}，可修改后重新保存`);
                  }}
                >
                  <td>
                    <strong>{position.symbol}</strong>
                  </td>
                  <td>{position.name}</td>
                  <td>{position.market}</td>
                  <td>{num(position.core_quantity)}</td>
                  <td>{num(position.tactical_quantity)}</td>
                  <td>{num(position.average_cost)}</td>
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
