import { apiFetch, readApiError } from "./writeApi";

export type AnalysisModelSelection = { model_profile_id?: string; model_configuration_hash: string };
export type AnalysisLaunchSelection = AnalysisModelSelection & { market_profile_ids: string[]; market_configuration_hash?: string };
type Input = { instrument_id: string; portfolio_id: string; source: "PORTFOLIO" | "WATCHLIST" | "RESEARCH"; evidence_ids?: string[] } & Partial<AnalysisLaunchSelection>;
const key = "investment_os_pending_analysis";
let pending: { fingerprint: string; requestId: string } | null = null;

async function submit(path: string, input: object): Promise<{ id: string }> {
  const fingerprint = JSON.stringify({ path, input });
  try { pending = JSON.parse(sessionStorage.getItem(key) ?? "null"); } catch { /* retain in-memory fallback */ }
  if (!pending || pending.fingerprint !== fingerprint) pending = { fingerprint, requestId: crypto.randomUUID() };
  try { sessionStorage.setItem(key, JSON.stringify(pending)); } catch { /* no secrets are stored */ }
  const response = await apiFetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...input, request_id: pending.requestId }),
  });
  if (!response.ok) throw new Error(await readApiError(response));
  const result = await response.json() as { id?: unknown };
  if (typeof result.id !== "string" || !result.id) throw new Error("任务响应不完整。请到分析运行核对，不要直接重复发起。");
  pending = null;
  try { sessionStorage.removeItem(key); } catch { /* optional */ }
  return { id: result.id };
}

export function submitAnalysis(input: Input) { return submit("/api/v1/analysis-jobs", input); }
export function retryAnalysis(runId: string) { return submit(`/api/v1/analysis-jobs/${encodeURIComponent(runId)}/retry`, {}); }
