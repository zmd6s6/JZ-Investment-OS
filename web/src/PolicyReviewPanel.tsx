import { useEffect, useState } from "react";

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

  if (error) return <p className="error-text">{error}</p>;
  if (!policy) return <p>加载中…</p>;

  return (
    <section className="legacy-page" aria-labelledby="policy-review-title">
      <h2 id="policy-review-title">Investment Policy（只读审阅）</h2>
      <p className="legacy-warning">{policy.warning}</p>
      <p>
        状态：<strong>{policy.policy_status}</strong> · 版本：
        <strong>{policy.active_policy_version}</strong>
        {policy.is_test_default ? " · TEST_DEFAULT" : ""}
      </p>
      {policy.limits.length === 0 ? (
        <p>未提供具体限额（不伪造数值）</p>
      ) : (
        <ul>
          {policy.limits.map((limit) => (
            <li key={limit.key}>
              {limit.key}: {limit.value}
            </li>
          ))}
        </ul>
      )}
      <label>
        <input
          type="checkbox"
          checked={acknowledged}
          onChange={(e) => setAcknowledged(e.target.checked)}
        />
        我已阅读当前政策状态（系统不会在此修改限额）
      </label>
    </section>
  );
}
