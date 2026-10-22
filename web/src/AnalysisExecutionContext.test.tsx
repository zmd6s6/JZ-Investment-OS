import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AnalysisExecutionContext } from "./AnalysisExecutionContext";

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const result = (id = "one") => ({ run_id: id, status: "RECORDED", receipt: { feature_snapshot_id: "actual-feature", request_input_hash: "a".repeat(64), runtime_input_hash: "b".repeat(64), recorded_at: "2026-10-22T07:01:00Z" }, valuation: { cash_balance: "10000.00", nav: null, base_currency: "CNY", as_of: "2026-10-22T07:00:00Z" } });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

it("reads the committed pre-model context only on explicit request and never writes", async () => {
  const fetcher = vi.fn().mockResolvedValue(json(result())); vi.stubGlobal("fetch", fetcher);
  render(<AnalysisExecutionContext runId="one" />);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "核对模型前估值快照" }));
  expect(await screen.findByText(/模型前上下文已固定/)).toBeVisible();
  expect(screen.getByText(/现金：10000 · 净值：未知 CNY/)).toBeVisible();
  expect(screen.getByText(/actual-feature/)).toBeVisible();
  expect(fetcher.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
});

it("shows old or not-yet-prepared input without inventing values", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ run_id: "one", status: "NOT_RECORDED", receipt: null, valuation: null })));
  render(<AnalysisExecutionContext runId="one" />);
  fireEvent.click(screen.getByRole("button", { name: "核对模型前估值快照" }));
  expect(await screen.findByText(/尚未保存本版模型前上下文/)).toBeVisible();
  expect(screen.queryByText(/现金：/)).not.toBeInTheDocument();
});

it("preserves verified content on read failure and permits a read-only retry", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(json(result())).mockResolvedValueOnce(json({}, 503)).mockResolvedValueOnce(json(result()));
  vi.stubGlobal("fetch", fetcher);
  render(<AnalysisExecutionContext runId="one" />);
  fireEvent.click(screen.getByRole("button", { name: "核对模型前估值快照" }));
  await screen.findByText(/actual-feature/);
  fireEvent.click(screen.getByRole("button", { name: "重新读取估值上下文" }));
  expect(await screen.findByRole("alert")).toBeVisible();
  expect(screen.getByText(/actual-feature/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "重新读取估值上下文" }));
  await screen.findByRole("button", { name: "重新读取估值上下文" });
});

it("rejects a response belonging to a different run", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(result("other"))));
  render(<AnalysisExecutionContext runId="one" />);
  fireEvent.click(screen.getByRole("button", { name: "核对模型前估值快照" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("响应不完整");
  expect(screen.queryByText(/actual-feature/)).not.toBeInTheDocument();
});

it("ignores late responses after switching runs", async () => {
  let finish!: (value: Response) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(resolve => { finish = resolve; })));
  const { rerender } = render(<AnalysisExecutionContext runId="one" />);
  fireEvent.click(screen.getByRole("button", { name: "核对模型前估值快照" }));
  rerender(<AnalysisExecutionContext runId="two" />);
  await act(async () => { finish(json(result())); });
  expect(screen.queryByText(/actual-feature/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "核对模型前估值快照" })).toBeEnabled();
});

it("ends a stalled read after the existing deadline without retrying providers", async () => {
  vi.useFakeTimers(); const fetcher = vi.fn(() => new Promise<Response>(() => {})); vi.stubGlobal("fetch", fetcher);
  render(<AnalysisExecutionContext runId="one" />);
  fireEvent.click(screen.getByRole("button", { name: "核对模型前估值快照" }));
  await act(async () => { await vi.advanceTimersByTimeAsync(15001); });
  expect(screen.getByRole("alert")).toHaveTextContent("超时");
  expect(screen.getByRole("button", { name: "核对模型前估值快照" })).toBeEnabled();
  expect(fetcher).toHaveBeenCalledTimes(1);
});
