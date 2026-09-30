import { useEffect, useState } from "react";

import { Panel } from "./ProductChrome";

type PolicyReview = {
  active_policy_version: string;
  policy_status: string;
  is_test_default: boolean;
  limits: { key: string; value: string }[];
  warning: string;
};

export function PolicyReviewPanel() {
  const [policy, setPolicy] = useState<PolicyReview | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void fetch("/api/v1/policy/review")
      .then((response) => {
        if (!response.ok) throw new Error("无法读取投资政策");
        return response.json() as Promise<PolicyReview>;
      })
      .then(setPolicy)
      .catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : "加载失败"),
      );
  }, []);

  return (
    <Panel
      title="Investment Policy · 只读审阅"
      description="这里只展示当前纪律状态，不能修改真实限额。"
      tone="warn"
    >
      {error ? <p className="banner banner-error">{error}</p> : null}
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

          {policy.limits.length === 0 ? (
            <p className="muted">未提供具体限额（不伪造数值）</p>
          ) : (
            <ul className="limit-list">
              {policy.limits.map((limit) => (
                <li key={limit.key}>
                  <span>{limit.key}</span>
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
