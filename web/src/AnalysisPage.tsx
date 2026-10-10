import { useCallback, useEffect, useState } from "react";

import { EmptyState, Panel, ProductChrome, StatusBanner } from "./ProductChrome";
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

  const load = useCallback(async () => {
    const response = await apiFetch("/api/v1/analysis-runs?limit=50");
    if (!response.ok) throw new Error(await readApiError(response));
    setRuns((await response.json()) as AnalysisSummary[]);
  }, []);

  useEffect(() => {
    void load().catch((reason: unknown) =>
      setError(reason instanceof Error ? reason.message : "加载失败"),
    );
  }, [load]);

  const openRun = useCallback(async (runId: string) => {
    const response = await apiFetch(`/api/v1/analysis-runs/${runId}`);
    if (!response.ok) throw new Error(await readApiError(response));
    setSelected((await response.json()) as AnalysisDetail);
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
            disabled={busy}
            onClick={() => void load()}
          >
            刷新运行列表
          </button>
        </div>
      </Panel>

      <Panel title="运行列表" description="最近的分析运行；点击查看详情。">
        {runs.length === 0 ? (
          <EmptyState title="暂无运行" hint="从组合页或观察清单发起一次分析。" />
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
                    <span className={`pill ${run.status === "SUCCEEDED" ? "valid" : "invalid"}`}>
                      {run.status === "SUCCEEDED" ? "成功" : "失败"}
                    </span>
                  </td>
                  <td>{run.source}</td>
                  <td>{run.policy_version_label}</td>
                  <td>{run.failure_code ?? "—"}</td>
                  <td>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => void openRun(run.id)}
                    >
                      查看
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
          title={`分析详情 · ${selected.status}`}
          description={`标的 ${selected.instrument_id} · 组合 ${selected.portfolio_id} · as-of ${new Date(selected.as_of).toLocaleString("zh-CN")}`}
        >
          {selected.failure_detail ? (
            <p className="banner banner-error">{selected.failure_detail}</p>
          ) : null}

          <h3>最终分析</h3>
          <div className="chip-row">
            <span className="chip ok">
              动作 {String(payload.decision?.action ?? "—")}
            </span>
            <span className="chip">风险 {String(payload.risk?.gate ?? "—")}</span>
            <span className="chip">Veto {String(payload.decision?.risk_veto ?? false)}</span>
            <span className="chip warn">{selected.policy_version_label}</span>
          </div>
          <p className="hint-text">
            证据 {payload.evidence_ids?.length ?? 0} 条 · Token{" "}
            {String(payload.token_usage?.total_tokens ?? "未知")} · 成本{" "}
            {String(payload.token_usage?.total_cost ?? "未知")}
          </p>
          {Array.isArray(payload.failures) && payload.failures.length > 0 ? (
            <p className="banner banner-error">限制：{payload.failures.join("、")}</p>
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
                  <td>{String(op.stance)}</td>
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
                  <td>{op.failure ? String(op.failure) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>估值与仓位</h3>
          <pre className="hint-text">
            {JSON.stringify(
              {
                valuation: payload.valuation,
                sizing: payload.sizing,
              },
              null,
              2,
            )}
          </pre>

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
