import { tokenPriceLabel } from "./analysisLabels";

const statuses: Record<string, string> = { SUCCEEDED: "报价齐全", PARTIAL: "部分缺价，继续下一来源", NO_DATA: "未取得可用报价", FAILED: "来源调用或报价校验失败", CONFIGURATION_CHANGED: "档案已改变，停止继续读取", CREDENTIAL_MISSING: "凭据不可用，停止继续读取" };
type Quote = { instrument_id: string; reference_price: string; currency: string; as_of: string };
type Attempt = { profile_id: string; name: string; provider_type: string; rank: number; status: string; queries: string[]; quotes?: Quote[] };

export function AnalysisMarketAudit({ value }: { value: unknown }) {
  if (!value || typeof value !== "object") return <p className="hint-text">本报告未记录行情尝试，可能是旧版或在结果保存前终止；不能据此判断来源未调用，不根据当前设置追补。</p>;
  const audit = value as { selection?: string; attempts?: Attempt[] };
  if (audit.selection === "NONE") return <p className="context-note">本次未选择行情源，没有自动调用已启用来源或使用合成报价。</p>;
  const attempts = Array.isArray(audit.attempts) ? audit.attempts : [];
  return <details><summary>行情来源实际尝试 · {attempts.length} 项</summary><p className="hint-text">只记录实际调用和校验结果，顺序来自本次确认；未列出的来源没有尝试。第二项及之后取得的报价标记为降级。</p>{attempts.length ? <ol className="tip-list">{attempts.map((a) => <li key={`${a.rank}-${a.profile_id}`}><strong>第 {a.rank + 1} 档 · {a.name} · {a.provider_type}</strong><p>{statuses[a.status] ?? a.status}；查询：{a.queries.join("、")}</p>{a.quotes?.map((q) => <p className="hint-text" key={q.instrument_id}>标的 {q.instrument_id} · {tokenPriceLabel(q.reference_price)} {q.currency} · 行情时点 {q.as_of}</p>)}</li>)}</ol> : <p>尚无实际行情尝试；不表示来源可用。</p>}</details>;
}
