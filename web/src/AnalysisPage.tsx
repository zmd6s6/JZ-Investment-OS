import { useCallback, useEffect, useRef, useState } from "react";

import { EmptyState, Panel, ProductChrome, StatusBanner } from "./ProductChrome";
import {
  actionLabel,
  explainFailure,
  gateLabel,
  runStatusLabel,
  stanceLabel,
} from "./analysisLabels";
import { apiFetch, readApiError } from "./writeApi";

const roleNames: Record<string, string> = { MACRO: "宏观研究", INDUSTRY: "行业研究", FUNDAMENTAL: "基本面研究", MARKET_QUANT: "市场与量化", EVENT: "事件研究", PORTFOLIO: "组合经理", RISK: "风险经理", DEVILS_ADVOCATE: "反方审查", CIO: "首席投资官" };

type AnalysisSummary = {
  id: string;
  instrument_id: string;
  portfolio_id: string;
  source: string;
  status: string;
  as_of: string;
  policy_version_label: string;
  failure_code: string | null;
  failure_detail: string | null;
  created_at: string;
  updated_at: string;
};

type AnalysisDetail = AnalysisSummary & {
  payload: Record<string, unknown>;
};

export function AnalysisPage() {
  const [runs, setRuns] = useState<AnalysisSummary[]>([]);
  const [selected, setSelected] = useState<AnalysisDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [portfolioFilter, setPortfolioFilter] = useState(() => {
    try { return sessionStorage.getItem("selected_portfolio_id") ?? ""; } catch { return ""; }
  });
  const reportRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(false);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [names, setNames] = useState<{ instruments: Record<string, string>; portfolios: Record<string, string> }>({ instruments: {}, portfolios: {} });
  const listInFlight = useRef(false);
  const detailInFlight = useRef(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const read = async (url: string): Promise<unknown[]> => {
        const response = await apiFetch(url);
        if (!response.ok) return [];
        const value: unknown = await response.json();
        return Array.isArray(value) ? value : [];
      };
      const [portfolios, watchlist] = await Promise.all([read("/api/v1/portfolios").catch(() => []), read("/api/v1/watchlist").catch(() => [])]);
      const instruments: Record<string, string> = {};
      const portfolioNames: Record<string, string> = {};
      const addInstrument = (raw: unknown) => {
        if (!raw || typeof raw !== "object") return;
        const row = raw as Record<string, unknown>;
        if (typeof row.instrument_id === "string" && typeof row.symbol === "string" && typeof row.name === "string") instruments[row.instrument_id] = `${row.symbol} ${row.name}`;
      };
      for (const raw of portfolios) {
        if (!raw || typeof raw !== "object") continue;
        const row = raw as Record<string, unknown>;
        if (typeof row.portfolio_id === "string" && typeof row.name === "string") portfolioNames[row.portfolio_id] = row.name;
        if (Array.isArray(row.positions)) row.positions.forEach(addInstrument);
      }
      watchlist.forEach(addInstrument);
      if (!cancelled) setNames({ instruments, portfolios: portfolioNames });
    })();
    return () => { cancelled = true; };
  }, []);

  const load = useCallback(async (showNotice = false) => {
    if (listInFlight.current) return;
    listInFlight.current = true;
    setLoading(true);
    setError(null);
    if (showNotice) setMessage(null);
    try {
    const portfolioId = portfolioFilter;
    const url = portfolioId
      ? `/api/v1/analysis-runs?portfolio_id=${encodeURIComponent(portfolioId)}&limit=50`
      : "/api/v1/analysis-runs?limit=50";
    const response = await apiFetch(url);
    if (!response.ok) throw new Error(await readApiError(response));
    setRuns((await response.json()) as AnalysisSummary[]);
    if (showNotice) setMessage("运行列表已更新。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "加载运行失败，请重试。");
    } finally {
      listInFlight.current = false;
      setLoading(false);
    }
  }, [portfolioFilter]);

  useEffect(() => {
    void load().catch((reason: unknown) =>
      setError(reason instanceof Error ? reason.message : "加载失败"),
    );
  }, [load]);

  useEffect(() => { if (selected) reportRef.current?.scrollIntoView?.({ block: "start" }); }, [selected]);

  const openRun = useCallback(async (runId: string) => {
    if (detailInFlight.current) return;
    detailInFlight.current = true;
    setOpeningId(runId);
    setError(null);
    setMessage(null);
    try {
    const response = await apiFetch(`/api/v1/analysis-runs/${runId}`);
    if (!response.ok) throw new Error(await readApiError(response));
    setSelected((await response.json()) as AnalysisDetail);
    setMessage("报告已加载，请查看下方分析详情。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "读取报告失败，请重试。");
    } finally {
      detailInFlight.current = false;
      setOpeningId(null);
    }
  }, []);

  const payload = (selected?.payload ?? {}) as {
    opinions?: unknown[];
    conflicts?: unknown[];
    decision?: Record<string, unknown>;
    risk?: Record<string, unknown>;
    valuation?: Record<string, unknown>;
    sizing?: unknown;
    failures?: string[];
    token_usage?: Record<string, unknown>;
    evidence_ids?: string[];
  };
  const riskGate = String(payload.risk?.gate ?? payload.decision?.risk_gate ?? "UNKNOWN");
  const riskVeto = payload.decision?.risk_veto === true || riskGate === "VETO" ? "是" : riskGate === "PASS" ? "否" : "未知（评估未提供）";

  return (
    <ProductChrome
      eyebrow="投资分析"
      title="分析运行"
      subtitle="从持仓或观察清单发起；结果只读保存，可刷新后继续查看。不产生订单。"
    >
      <div className="action-feedback">
      <StatusBanner kind="error" text={error} />
      <StatusBanner kind="ok" text={message} />
      <StatusBanner kind="info" text={loading ? "正在读取运行列表，请稍候…" : openingId ? "正在读取分析报告，请稍候…" : null} />
      </div>

      <Panel
        title="查找与阅读报告"
        description="列表状态表示流程是否结束，不代表观点可信或可以买入；请继续查看风险和数据限制。"
      >
        <p className="hint-text">
          新研究请在「资产组合 / 观察清单」页对单个标的点「立即分析」。报告会保存，刷新页面不会丢失。
        </p>
        <div className="btn-row">
          <a className="btn" href="/portfolio#holdings">分析已有持仓</a><a className="btn" href="/watchlist">分析观察标的</a>
          <button
            type="button"
            className="btn"
            disabled={loading || openingId !== null}
            onClick={() => void load(true)}
          >
            {loading ? "正在刷新…" : "刷新运行列表"}
          </button>
        </div>
        <p className="hint-text">{portfolioFilter ? "范围：当前选中的组合。找不到其他组合的报告？" : "范围：全部组合的最近 50 次运行。"}</p>
        {portfolioFilter ? <button type="button" className="btn ghost" disabled={loading || openingId !== null} onClick={() => { setSelected(null); setPortfolioFilter(""); }}>查看全部组合报告</button> : null}
      </Panel>

      <Panel title="运行列表" description="最近的分析运行；点击查看详情。">
        {runs.length === 0 ? (
          <EmptyState title={loading ? "正在加载运行" : error ? "暂时无法读取运行" : "暂无运行"} hint={loading ? "请稍候，尚未完成读取。" : error ? "请根据上方提示处理，然后刷新运行列表。" : "从组合页或观察清单发起一次分析。"} />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>标的 / 组合</th>
                <th>状态</th>
                <th>来源</th>
                <th>政策版本</th>
                <th>失败</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id}>
                  <td>{new Date(run.created_at).toLocaleString("zh-CN")}</td>
                  <td><strong>{names.instruments[run.instrument_id] ?? `标的 ${run.instrument_id.slice(0, 8)}…`}</strong><div className="muted">{names.portfolios[run.portfolio_id] ?? `组合 ${run.portfolio_id.slice(0, 8)}…`}</div></td>
                  <td>
                    <span
                      className={`pill ${
                        run.status === "SUCCEEDED"
                          ? "valid"
                          : run.status === "RUNNING"
                            ? "warn"
                            : "invalid"
                      }`}
                    >
                      {runStatusLabel(run.status)}
                    </span>
                  </td>
                  <td>{run.source === "PORTFOLIO" ? "持仓" : run.source === "WATCHLIST" ? "观察清单" : run.source}</td>
                  <td>{run.policy_version_label}</td>
                  <td>{run.failure_code ? explainFailure(run.failure_code) : "—"}</td>
                  <td>
                    <button
                      type="button"
                      className="btn"
                      disabled={openingId !== null}
                      onClick={() => void openRun(run.id)}
                    >
                      {openingId === run.id ? "正在读取…" : "查看"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      {selected ? (
        <div ref={reportRef} id="analysis-report">
        <Panel
          title={`分析详情 · ${runStatusLabel(selected.status)}`}
          description={`分析时点 ${new Date(selected.as_of).toLocaleString("zh-CN")} · 政策版本 ${selected.policy_version_label}`}
        >
          <p><strong>{names.instruments[selected.instrument_id] ?? "标的名称暂不可读取"}</strong> · {names.portfolios[selected.portfolio_id] ?? "组合名称暂不可读取"}</p>
          <p className="hint-text">名称来自当前持仓 / 观察档案，只作导航；历史分析仍以固定标识与输入快照为准。</p>
          <details><summary>运行与关联标识</summary><p className="hint-text">运行 {selected.id} · 标的 {selected.instrument_id} · 组合 {selected.portfolio_id}</p></details>
          {selected.policy_version_label.includes("TEST_DEFAULT") ? <p className="context-note">当前使用 TEST_DEFAULT 测试政策，不是真实投资限额，不允许据此增加暴露。这里不会自动激活或修改政策。</p> : null}
          {selected.failure_detail || selected.failure_code ? (
            <p className="banner banner-error">
              {selected.failure_code ? `${explainFailure(selected.failure_code)}：` : ""}
              {selected.failure_detail ?? "分析未完成。"}
            </p>
          ) : null}

          <h3>最终分析</h3>
          <div className="chip-row">
            <span className="chip">
              动作 {actionLabel(String(payload.decision?.action ?? "—"))}
            </span>
            <span className="chip">
              风险门 {gateLabel(riskGate)}
            </span>
            <span className="chip">
              风险否决 {riskVeto}
            </span>
            <span className="chip warn">{selected.policy_version_label}</span>
          </div>
          <p className="hint-text">
            证据 {payload.evidence_ids?.length ?? 0} 条 · Token{" "}
            {String(payload.token_usage?.total_tokens ?? "未知")} · 成本{" "}
            {String(payload.token_usage?.total_cost ?? "未知")}
          </p>
          {Array.isArray(payload.failures) && payload.failures.length > 0 ? (
            <div className="banner banner-error">
              <strong>本轮限制（失败关闭，不会给出买入）：</strong>
              <ul className="failure-list">
                {payload.failures.map((code) => (
                  <li key={code}>{explainFailure(code)}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <h3>团队协作与分歧</h3>
          <p className="context-note">协作协议：专家独立分析 → 冲突检测 → 定向质疑与反方审查（最多两轮）→ 组合经理 / 风险经理 → 确定性规则 → 最终建议。此处说明协议，不代表实时执行进度。</p>
          {payload.conflicts?.length ? <ul className="tip-list">{(payload.conflicts as Record<string, unknown>[]).map((conflict, index) => <li key={index}>分歧类型 {String(conflict.kind ?? "未提供")} · 参与角色 {Array.isArray(conflict.roles) ? conflict.roles.map((role) => roleNames[String(role)] ?? String(role)).join("、") : "未提供"}</li>)}</ul> : <p className="hint-text">本报告未提供冲突记录；这不代表所有角色观点一致。</p>}
          <h3>投资团队意见</h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>角色</th>
                <th>立场</th>
                <th>置信度</th>
                <th>模型</th>
                <th>要点</th>
                <th>失败</th>
              </tr>
            </thead>
            <tbody>
              {((payload.opinions as Record<string, unknown>[]) ?? []).map((op) => (
                <tr key={String(op.role)}>
                  <td>{roleNames[String(op.role)] ?? String(op.role)}<div className="muted">{String(op.role)}</div></td>
                  <td>{stanceLabel(String(op.stance))}</td>
                  <td>{String(op.confidence)}</td>
                  <td>
                    {String(op.model_name ?? "—")}
                    <div className="muted">{String(op.model_provider ?? "")}</div>
                  </td>
                  <td>
                    {(Array.isArray(op.claims) ? op.claims : []).slice(0, 2).map((c, i) => (
                      <div key={i} className="muted">
                        {String((c as { claim?: string }).claim ?? "")}
                      </div>
                    ))}
                    <details><summary>完整观点 / 引用 / 未知项</summary>
                      {(Array.isArray(op.claims) ? op.claims : []).map((claim, index) => <div key={index}><p>{String((claim as { claim?: unknown }).claim ?? "未提供")}</p><p className="muted">证据引用：{Array.isArray((claim as { evidence_ids?: unknown }).evidence_ids) ? ((claim as { evidence_ids: unknown[] }).evidence_ids).map(String).join("、") : "未提供"}</p></div>)}
                      <p>假设：{Array.isArray(op.assumptions) && op.assumptions.length ? op.assumptions.map(String).join("；") : "未提供"}</p>
                      <p>未知项：{Array.isArray(op.unknowns) && op.unknowns.length ? op.unknowns.map(String).join("；") : "未提供"}</p>
                    </details>
                  </td>
                  <td>{op.failure ? explainFailure(String(op.failure)) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <details><summary>查看风险旗与解除条件</summary>{Array.isArray(payload.risk?.flags) && payload.risk.flags.length ? <ul className="tip-list">{(payload.risk.flags as Record<string, unknown>[]).map((flag, index) => <li key={index}>{String(flag.code ?? "未提供")} · {String(flag.severity ?? "未提供")}<p>解除条件：{String(flag.release_condition ?? "未提供")}</p><p className="muted">证据引用：{Array.isArray(flag.evidence_ids) ? flag.evidence_ids.map(String).join("、") : "未提供"}</p></li>)}</ul> : <p className="hint-text">未提供风险旗，不代表风险已经排除。</p>}</details>

          <h3>估值与仓位</h3>
          {payload.failures?.includes("MISSING_REFERENCE_QUOTES") ? (
            <p className="banner banner-info">未配置可用行情或未获取到报价：可继续阅读研究意见，暂不能计算完整市值和建议数量。可在设置中配置已授权的行情源；没有 Tushare Token 不影响其他已配置功能。</p>
          ) : null}
          <p className="hint-text">
            行情来源：
            {String((payload.valuation as { source?: string } | undefined)?.source ?? "未提供")}
            {String((payload.valuation as { degraded?: boolean } | undefined)?.degraded) ===
            "true"
              ? "（降级源）"
              : ""}
          </p>
          <details><summary>查看估值与仓位技术数据</summary><pre className="hint-text">
            {JSON.stringify(
              {
                valuation: payload.valuation,
                sizing: payload.sizing,
              },
              null,
              2,
            )}
          </pre></details>

          {selected.status === "SUCCEEDED" ? (
            <p className="banner banner-ok">
              本结果为只读影子分析；批准与执行属于后续阶段，当前不提交任何订单。
            </p>
          ) : null}
        </Panel>
        </div>
      ) : null}
    </ProductChrome>
  );
}

export { AnalysisPage as default };
