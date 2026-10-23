import { afterEach, expect, it, vi } from "vitest";
import { submitAnalysis } from "./analysisSubmission";

const input = { instrument_id: "synthetic-target", portfolio_id: "synthetic-portfolio", source: "RESEARCH" as const, evidence_ids: ["synthetic-evidence"] };
afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });

it("reuses the submission UUID after a lost response, but a new confirmed run gets a new UUID", async () => {
  const fetcher = vi.fn().mockRejectedValueOnce(new Error("synthetic response lost"))
    .mockImplementation(async () => new Response(JSON.stringify({ id: "synthetic-run" })));
  vi.stubGlobal("fetch", fetcher);
  await expect(submitAnalysis(input)).rejects.toThrow("无法连接本地服务");
  await submitAnalysis(input);
  await submitAnalysis(input);
  const ids = fetcher.mock.calls.map(([, init]) => JSON.parse(init.body).request_id);
  expect(ids[0]).toBe(ids[1]);
  expect(ids[2]).not.toBe(ids[1]);
  expect(sessionStorage.getItem("investment_os_pending_analysis")).toBeNull();
});

it("never falls back to synchronous paid analysis when the queue endpoint is unavailable", async () => {
  const fetcher = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({ detail: "analysis_jobs_unavailable" }), { status: 503 }));
  vi.stubGlobal("fetch", fetcher);
  await expect(submitAnalysis(input)).rejects.toThrow("后台分析服务尚未部署");
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][0]).toBe("/api/v1/analysis-jobs");
});
