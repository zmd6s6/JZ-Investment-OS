import { useState, type ComponentProps } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AnalysisJobPanel } from "./AnalysisJobPanel";

const run: ComponentProps<typeof AnalysisJobPanel>["run"] = { id: "synthetic-run", status: "RUNNING", failure_code: null, failure_detail: null, updated_at: "2026-10-16T00:00:00Z", payload: { execution_mode: "BACKGROUND", stage: "ROUND_ONE" } };
const rows = [{ id: "event-one", sequence: 1, stage: "ROUND_ONE", state: "STARTED", occurred_at: run.updated_at }];
const json = (value: unknown) => new Response(JSON.stringify(value));
function Harness({ value = run }: { value?: typeof run }) { const [current, setCurrent] = useState(value); return <><p data-testid="status">{current.status}</p><AnalysisJobPanel run={current} onUpdate={setCurrent} /></>; }
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); sessionStorage.clear(); });

it("keeps polling task status when progress history never responds", async () => {
  vi.useFakeTimers();
  let reads = 0;
  const fetcher = vi.fn((url: string) => url.endsWith("/progress")
    ? new Promise<Response>(() => {})
    : Promise.resolve(json(++reads === 1 ? run : { ...run, status: "SUCCEEDED", payload: { ...run.payload, stage: "FINISHED" } })));
  vi.stubGlobal("fetch", fetcher);
  render(<Harness />);
  await act(async () => { await vi.advanceTimersByTimeAsync(2001); });
  expect(screen.getByTestId("status")).toHaveTextContent("SUCCEEDED");
  expect(reads).toBe(2);
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith("/progress"))).toHaveLength(1);
});

it("takes a final history snapshot if status ended while an older history read was in flight", async () => {
  vi.useFakeTimers();
  let releaseStatus!: (value: Response) => void;
  let releaseHistory!: (value: Response) => void;
  let historyReads = 0;
  vi.stubGlobal("fetch", vi.fn((url: string) => !url.endsWith("/progress")
    ? new Promise<Response>((resolve) => { releaseStatus = resolve; })
    : ++historyReads === 1 ? new Promise<Response>((resolve) => { releaseHistory = resolve; })
      : Promise.resolve(json([{ ...rows[0], stage: "FINISHED", state: "COMPLETED" }]))));
  render(<Harness />);
  await act(async () => releaseStatus(json({ ...run, status: "SUCCEEDED" })));
  await act(async () => releaseHistory(json(rows)));
  await act(async () => { await vi.advanceTimersByTimeAsync(2001); });
  expect(screen.getByText(/任务结束.*完成/)).toBeVisible();
  expect(historyReads).toBe(2);
});

it("bounds stalled history reads and refreshes without submitting another analysis", async () => {
  vi.useFakeTimers();
  let stalled = true;
  const fetcher = vi.fn((url: string, init?: RequestInit) => url.endsWith("/progress") && stalled
    ? new Promise<Response>(() => {})
    : Promise.resolve(json(url.endsWith("/progress") ? rows : { ...run, status: "SUCCEEDED" })));
  vi.stubGlobal("fetch", fetcher);
  render(<Harness />);
  await act(async () => { await vi.advanceTimersByTimeAsync(15001); });
  expect(screen.getByRole("alert")).toHaveTextContent("阶段历史读取超时");
  expect(screen.getByTestId("status")).toHaveTextContent("SUCCEEDED");
  stalled = false;
  fireEvent.click(screen.getByRole("button", { name: "刷新任务进度" }));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByText(/第一轮.*开始/)).toBeVisible();
  expect(fetcher.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
});

it("loads real stage events without submitting models and explains cancellation cost", async () => {
  const fetcher = vi.fn((url: string, init?: RequestInit) => Promise.resolve(json(init?.method === "POST" ? { ...run, payload: { ...run.payload, stage: "CANCEL_REQUESTED" } } : url.endsWith("/progress") ? rows : run)));
  vi.stubGlobal("fetch", fetcher);
  render(<Harness />);
  expect(await screen.findByText(/第一轮.*开始/)).toBeVisible();
  expect(fetcher.mock.calls.every(([, init]) => !init?.method)).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "请求取消" }));
  expect(screen.getByRole("region", { name: "任务操作确认" })).toHaveTextContent("可能完成、修复和计费");
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "确认请求取消" }));
  expect(await screen.findByText(/取消请求已记录/)).toBeVisible();
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
});

it("discards a running response that arrives after cancellation", async () => {
  let release!: (value: Response) => void;
  let reads = 0;
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith("/progress")) return Promise.resolve(json(rows));
    if (init?.method === "POST") return Promise.resolve(json({ ...run, status: "CANCELLED" }));
    return ++reads === 1 ? new Promise<Response>((resolve) => { release = resolve; }) : Promise.resolve(json({ ...run, status: "CANCELLED" }));
  }));
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "请求取消" }));
  fireEvent.click(screen.getByRole("button", { name: "确认请求取消" }));
  await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("CANCELLED"));
  await act(async () => release(json(run)));
  expect(screen.getByTestId("status")).toHaveTextContent("CANCELLED");
});

it("requires independent confirmation before a paid new run", async () => {
  const failed = { ...run, status: "FAILED" };
  const fetcher = vi.fn((url: string) => Promise.resolve(json(url.endsWith("/progress") ? rows : failed)));
  vi.stubGlobal("fetch", fetcher);
  render(<Harness value={failed} />);
  fireEvent.click(screen.getByRole("button", { name: "重新发起新运行" }));
  expect(screen.getByRole("region", { name: "任务操作确认" })).toHaveTextContent("可能再次计费");
  expect(fetcher.mock.calls.some(([url]) => url.endsWith("/retry"))).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "暂不操作" }));
  expect(screen.queryByRole("region", { name: "任务操作确认" })).not.toBeInTheDocument();
});

it("does not invent progress for legacy reports", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<Harness value={{ ...run, payload: {} }} />);
  expect(screen.getByText(/不追补或伪造进度/)).toBeVisible();
  expect(fetcher).not.toHaveBeenCalled();
});
