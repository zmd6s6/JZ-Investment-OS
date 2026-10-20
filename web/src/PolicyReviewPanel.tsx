import { useEffect, useState } from "react";

import { Panel } from "./ProductChrome";
import { readAnalysisJson } from "./analysisReads";
import { POLICY_LIMIT_NAMES } from "./AnalysisGovernance";

type PolicyReview = {
  active_policy_version: string;
  policy_status: string;
  is_test_default: boolean;
  limits?: { key: string; value: string }[] | null;
  warning?: string | null;
  snapshot?: { policy_version_id?: string | null; content_hash?: string } | null;
};

function normalizePolicy(raw: unknown): PolicyReview {
  const obj = (raw ?? {}) as Partial<PolicyReview>;
  if (typeof obj.active_policy_version !== "string" || typeof obj.policy_status !== "string" || typeof obj.is_test_default !== "boolean" || !Array.isArray(obj.limits)) throw new Error("政策响应不完整，未采用该响应；请重新读取。");
  return {
    active_policy_version: obj.active_policy_version ?? "none",
    policy_status: obj.policy_status ?? "TEST_DEFAULT",
    is_test_default: Boolean(obj.is_test_default),
    limits: Array.isArray(obj.limits) ? obj.limits : [],
    warning: obj.warning ?? "TEST_DEFAULT 不是投资建议.",
    snapshot: obj.snapshot,
  };
}

export function PolicyReviewPanel() {
  const [policy, setPolicy] = useState<PolicyReview | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [portfolioId] = useState(() => {
    try { return sessionStorage.getItem("selected_portfolio_id") ?? ""; } catch { return ""; }
  });

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(null); setPolicy(null); setAcknowledged(false);
    void readAnalysisJson<unknown>(`/api/v1/policy/review${portfolioId ? `?portfolio_id=${encodeURIComponent(portfolioId)}` : ""}`, controller.signal, "读取政策")
      .then((raw) => { if (!controller.signal.aborted) setPolicy(normalizePolicy(raw)); })
      .catch((reason: unknown) =>
        { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "加载失败"); },
      ).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [portfolioId, refresh]);

  const limits = policy?.limits ?? [];

  return (
    <Panel
      title="投资政策 · 只读审阅"
      description="这里只展示当前纪律状态，不能修改真实限额。"
      tone="warn"
    >
      {error ? <p className="banner banner-error">{error}</p> : null}
      <p className="hint-text">范围：{portfolioId ? "当前选中的组合" : "全局回退政策（尚未选择组合）"}。历史分析请查看报告内的固定快照。</p>
      <button type="button" className="btn ghost" disabled={loading} onClick={() => setRefresh((value) => value + 1)}>{loading ? "正在读取政策…" : "重新读取政策"}</button>
      {!policy && !error ? <p>加载中…</p> : null}
      {policy ? (
        <div className="policy-layout">
          <div className="policy-summary">
            <div>
              <span>状态</span>
              <strong data-testid="policy-status">{policy.policy_status}</strong>
            </div>
            <div>
              <span>版本</span>
              <strong>{policy.active_policy_version}</strong>
            </div>
            {policy.is_test_default ? (
              <div>
                <span>标记</span>
                <strong>TEST_DEFAULT</strong>
              </div>
            ) : null}
          </div>

          <p className="banner banner-info">{policy.warning}</p>
          {policy.snapshot ? <p className="hint-text" style={{ overflowWrap: "anywhere" }}>版本 ID：{policy.snapshot.policy_version_id ?? "无真实批准版本"} · 内容摘要 {policy.snapshot.content_hash ?? "未记录"}</p> : null}

          {limits.length === 0 ? (
            <p className="muted">未提供具体限额（不伪造数值）</p>
          ) : (
            <ul className="limit-list">
              {limits.map((limit) => (
                <li key={limit.key}>
                  <span>{POLICY_LIMIT_NAMES[limit.key] ?? limit.key}</span>
                  <strong>{limit.value}</strong>
                </li>
              ))}
            </ul>
          )}

          <label className="check-line">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
            />
            <span>我已阅读当前政策状态（系统不会在此修改限额）</span>
          </label>
          {acknowledged ? (
            <p className="banner banner-ok">已记录你的审阅确认（本地界面状态，不改政策）。</p>
          ) : null}
        </div>
      ) : null}
    </Panel>
  );
}
