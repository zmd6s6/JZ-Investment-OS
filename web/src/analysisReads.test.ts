import { afterEach, expect, it, vi } from "vitest";
import { ANALYSIS_READ_TIMEOUT_MS, readAnalysisJson } from "./analysisReads";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it("reads fresh JSON without submitting a write and releases its deadline", async () => {
  vi.useFakeTimers();
  const fetcher = vi.fn().mockResolvedValue(new Response('{"status":"SUCCEEDED"}'));
  vi.stubGlobal("fetch", fetcher);
  expect(await readAnalysisJson("/api/v1/analysis-runs/synthetic")).toEqual({ status: "SUCCEEDED" });
  expect(fetcher).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ cache: "no-store" }));
  expect(fetcher.mock.calls[0][1].method).toBeUndefined();
  expect(vi.getTimerCount()).toBe(0);
});

it("bounds a fetch that ignores abort, without automatic retry", async () => {
  vi.useFakeTimers();
  const fetcher = vi.fn(() => new Promise<Response>(() => {}));
  vi.stubGlobal("fetch", fetcher);
  const failure = expect(readAnalysisJson("/api/v1/analysis-runs/synthetic")).rejects.toThrow("读取分析记录超时");
  await vi.advanceTimersByTimeAsync(ANALYSIS_READ_TIMEOUT_MS);
  await failure;
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(vi.getTimerCount()).toBe(0);
});

it("also bounds body parsing after response headers arrive", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: () => new Promise(() => {}) }));
  const failure = expect(readAnalysisJson("/api/v1/analysis-runs/synthetic/progress", undefined, "阶段历史读取")).rejects.toThrow("阶段历史读取超时");
  await vi.advanceTimersByTimeAsync(ANALYSIS_READ_TIMEOUT_MS);
  await failure;
});

it("cancels an in-flight read on unmount without waiting for the deadline", async () => {
  vi.useFakeTimers();
  let requestSignal: AbortSignal | undefined;
  const fetcher = vi.fn((_url: string, init: RequestInit) => { requestSignal = init.signal as AbortSignal; return new Promise<Response>(() => {}); });
  vi.stubGlobal("fetch", fetcher);
  const owner = new AbortController();
  const failure = expect(readAnalysisJson("/api/v1/analysis-runs/synthetic", owner.signal)).rejects.toThrow("读取已取消");
  owner.abort();
  await failure;
  expect(requestSignal?.aborted).toBe(true);
  expect(vi.getTimerCount()).toBe(0);
});

it("does not start a read for an already abandoned page", async () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  const owner = new AbortController(); owner.abort();
  await expect(readAnalysisJson("/api/v1/analysis-runs/synthetic", owner.signal)).rejects.toThrow("读取已取消");
  expect(fetcher).not.toHaveBeenCalled();
});

it("keeps HTTP failures explicit without echoing untrusted details", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"detail":"合成内部错误不应回显"}', { status: 503 })));
  await expect(readAnalysisJson("/api/v1/analysis-runs/synthetic")).rejects.toThrow("HTTP 503");
});

it("does not echo malformed response text in JSON errors", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("合成坏数据不应回显")));
  await expect(readAnalysisJson("/api/v1/analysis-runs/synthetic")).rejects.toThrow("分析记录格式异常");
});
