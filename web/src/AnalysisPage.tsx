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
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const listInFlight = useRef(false);
  const detailInFlight = useRef(false);

  const load = useCallback(async (showNotice = false) => {
    if (listInFlight.current) return;
    listInFlight.current = true;
    setLoading(true);
    setError(null);
    if (showNotice) setMessage(null);
    try {
    let portfolioId = "";
    try {
      portfolioId = sessionStorage.getItem("selected_portfolio_id") ?? "";
    } catch {
      portfolioId = "";
    }
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
  }, []);

  useEffect(() => {
    void load().catch((reason: unknown) =>
      setError(reason instanceof Error ? reason.message : "加载失败"),
    );
  }, [load]);

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

  async function startFor(
    instrumentId: string,
    portfolioId: string,
    source: "PORTFOLIO" | "WATCHLIST",
  ) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const response = await apiFetch("/api/v1/analysis-runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          instrument_id: instrumentId,
          portfolio_id: portfolioId,
          source,
        }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const run = (await response.json()) as AnalysisDetail;
      setSelected(run);
      setMessage(
        run.status === "SUCCEEDED"
          ? "分析已完成"
          : `分析未成功：${run.failure_code ?? run.status}`,
      );
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "启动分析失败");
    } finally {
      setBusy(false);
    }
  }

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

  return (
    <ProductChrome
      eyebrow="投资分析"
      title="分析运行"
      subtitle="从持仓或观察清单发起；结果只读保存，可刷新后继续查看。不产生订单。"
    >
      <StatusBanner kind="error" text={error} />
      <StatusBanner kind="ok" text={message} />
      <StatusBanner kind="info" text={loading ? "正在读取运行列表，请稍候…" : openingId ? "正在读取分析报告，请稍候…" : null} />

      <Panel
        title="启动一次分析"
        description="需要先有组合上下文与已配置模型。缺少 Evidence 或模型时会明确失败。"
      >
        <p className="hint-text">
          也可在「资产组合 / 观察清单」页对单个标的点「立即分析」。
        </p>
        <div className="btn-row">
          <button
            type="button"
            className="btn"
            disabled={busy || loading || openingId !== null}
            onClick={() => void load(true)}
          >
            {loading ? "正在刷新…" : "刷新运行列表"}
          </button>
        </div>
      </Panel>

      <Panel title="运行列表" description="最近的分析运行；点击查看详情。">
        {runs.length === 0 ? (
          <EmptyState title={loading ? "正在加载运行" : error ? "暂时无法读取运行" : "暂无运行"} hint={loading ? "请稍候，尚未完成读取。" : error ? "请根据上方提示处理，然后刷新运行列表。" : "从组合页或观察清单发起一次分析。"} />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>时间</th>
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
                  <td>{run.source}</td>
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
        <Panel
          title={`分析详情 · ${runStatusLabel(selected.status)}`}
          description={`标的 ${selected.instrument_id} · 组合 ${selected.portfolio_id} · as-of ${new Date(selected.as_of).toLocaleString("zh-CN")}`}
        >
          {selected.failure_detail || selected.failure_code ? (
            <p className="banner banner-error">
              {selected.failure_code ? `${explainFailure(selected.failure_code)}：` : ""}
              {selected.failure_detail ?? "分析未完成。"}
            </p>
          ) : null}

          <h3>最终分析</h3>
          <div className="chip-row">
            <span className="chip ok">
              动作 {actionLabel(String(payload.decision?.action ?? "—"))}
            </span>
            <span className="chip">
              风险门 {gateLabel(String(payload.risk?.gate ?? "—"))}
            </span>
            <span className="chip">
              风险否决 {payload.decision?.risk_veto ? "是" : "否"}
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
                  <td>{String(op.role)}</td>
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
                  </td>
                  <td>{op.failure ? explainFailure(String(op.failure)) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>

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
      ) : null}
    </ProductChrome>
  );
}

export { AnalysisPage as default };
