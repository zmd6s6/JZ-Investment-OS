import { useCallback, useEffect, useState } from "react";
import { Panel } from "./ProductChrome";

type Item = {
  source_id: string;
  source: "DECISION" | "DAILY_TASK" | "MONTHLY_TASK";
  status: string;
  observed_at: string;
  detail_url: string;
  description: string;
};
type Section = {
  state: "AVAILABLE" | "EMPTY" | "ERROR" | "NOT_PROVIDED";
  items: Item[];
  limited: boolean;
  message: string;
};
type Inbox = {
  schema_version: "1.0";
  as_of: string;
  auto_trade: false;
  pending_approvals: Section;
  degraded_runs: Section;
  action_required: Section;
  hold_watch: Section;
  new_opportunity: Section;
  risk_veto: Section;
};
const sections: { key: keyof Omit<Inbox, "schema_version" | "as_of" | "auto_trade">; label: string }[] = [
  { key: "pending_approvals", label: "待处理人工审批" },
  { key: "degraded_runs", label: "失败或降级的运行" },
  { key: "action_required", label: "需要关注" },
  { key: "hold_watch", label: "持有与观察" },
  { key: "new_opportunity", label: "新机会" },
  { key: "risk_veto", label: "风险否决" },
];
function valid(value: unknown): value is Inbox {
  if (!value || typeof value !== "object") return false;
  const data = value as Partial<Inbox>;
  return data.schema_version === "1.0" && data.auto_trade === false &&
    typeof data.as_of === "string" &&
    sections.every(({ key }) => {
      const s = data[key];
      return s && ["AVAILABLE", "EMPTY", "ERROR", "NOT_PROVIDED"].includes(s.state) &&
        typeof s.message === "string" && Array.isArray(s.items) &&
        typeof s.limited === "boolean" &&
        s.items.every((item) => typeof item.source_id === "string" &&
          typeof item.description === "string" && typeof item.observed_at === "string" &&
          ((item.source === "DECISION" && item.detail_url === `/decisions?decision_id=${item.source_id}`) ||
            (["DAILY_TASK", "MONTHLY_TASK"].includes(item.source) && item.detail_url === `/calendar#${item.source.toLowerCase()}-${item.source_id}`)));
    });
}
export function OperationalInbox() {
  const [data, setData] = useState<Inbox | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch("/api/v1/operational-inbox", { signal: controller.signal });
      if (!response.ok) throw new Error("运营状态读取失败");
      const body: unknown = await response.json();
      if (!valid(body)) throw new Error("运营状态协议无效");
      setData(body);
    } catch {
      setData(null);
      setError("无法确认当前运营状态，请稍后刷新；不代表没有待办。");
    } finally {
      window.clearTimeout(timer);
      setLoading(false);
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  return <Panel title="运营待办" description="只读持久化状态；不会审批、重试或发起研究。"
    actions={<button type="button" className="btn" disabled={loading} onClick={() => void refresh()}>
      {loading ? "刷新中…" : "刷新运营状态"}
    </button>}>
    {error && <p role="alert">{error}</p>}
    {!data && !error && <p role="status">正在读取运营状态…</p>}
    {data && <p>读取时间 {data.as_of}</p>}
    {data && <div className="capability-grid">
      {sections.map(({ key, label }) => {
        const section = data[key];
        return <section key={key} className="capability-card" aria-label={label}>
          <h3>{label}</h3>
          <p>{section.state === "NOT_PROVIDED" ? "未提供" :
            section.state === "ERROR" ? "部分或全部读取失败" :
              section.state === "EMPTY" ? "暂无记录" : "已读取"}</p>
          <p>{section.message}</p>
          {section.items.map((item) => <p key={item.source + item.source_id}>
            <a href={item.detail_url}>{item.description}</a>
            <small> · {item.observed_at} · 来源 {item.source_id}</small>
          </p>)}
          {section.limited && <p>仅展示前20条，非完整总数。</p>}
        </section>;
      })}
    </div>}
  </Panel>;
}
