import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { EvidenceReaderProvider, EvidenceReferences } from "./AnalysisEvidence";

const R = "10000000-0000-4000-8000-000000000001", R2 = "10000000-0000-4000-8000-000000000002";
const A = "20000000-0000-4000-8000-000000000001", B = "20000000-0000-4000-8000-000000000002";
const value = (id = A, run = R) => ({ schema_version: "1.0", run_id: run, evidence_id: id, status: "VERIFIED", input_hash: "b".repeat(64), analysis_as_of: "2026-10-15T08:00:00Z", read_at: "2026-10-23T08:00:00Z", untrusted_content: true, title: `已保存标题 ${id}`, title_truncated: false, freshness_at_run: "FRESH", freshness_now: "EXPIRED", texts: [{ field: "content", text: "<img src='https://untrusted.example.test/image' onerror='bad()'>保存片段，不执行", original_length: 100, truncated: true }], citation: { evidence_id: id, content_hash: "a".repeat(64), source_name: "合成来源", source_locator: "https://source.example.test/article", source_tier: "OTHER", provider: "SYNTHETIC", observed_at: "2026-10-15T07:00:00Z", effective_at: "2026-10-15T07:00:00Z", available_at: "2026-10-15T07:00:00Z", ingested_at: "2026-10-15T07:00:00Z", expires_at: "2026-10-20T07:00:00Z", summary: "当时摘要" } });
const response = (body: unknown, status = 200) => ({ ok: status === 200, status, json: async () => body });
function Harness({ run = R }: { run?: string }) { return <EvidenceReaderProvider key={run} runId={run}><EvidenceReferences ids={[A, B]} /></EvidenceReaderProvider>; }
const open = (id = A) => fireEvent.click(screen.getByRole("button", { name: `查看引用资料 ${id}` }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

it("loads only on explicit citation click, renders escaped saved text and returns focus to the report", async () => {
  const fetcher = vi.fn().mockResolvedValue(response(value())); vi.stubGlobal("fetch", fetcher);
  render(<Harness />); expect(fetcher).not.toHaveBeenCalled();
  const trigger = screen.getByRole("button", { name: `查看引用资料 ${A}` }); trigger.focus(); open();
  expect(await screen.findByText("已核对：存储内容与本次引用一致。")).toBeVisible();
  expect(screen.getByRole("dialog", { name: "当次引用资料" })).toBeVisible();
  expect(screen.getByText(/已过期，仅供历史核对/)).toBeVisible();
  expect(screen.getByText(/<img src=/)).toBeVisible(); expect(document.querySelector("img")).toBeNull();
  expect(screen.getByText(/内容已截断/)).toBeVisible();
  const link = screen.getByRole("link", { name: "在新标签打开来源（将联网）" });
  expect(link).toHaveAttribute("target", "_blank"); expect(link).toHaveAttribute("rel", "noopener noreferrer");
  expect(fetcher).toHaveBeenCalledTimes(1); expect(fetcher.mock.calls[0][0]).toBe(`/api/v1/analysis-runs/${R}/evidence/${A}`);
  fireEvent.click(screen.getByRole("button", { name: "关闭资料，返回报告" }));
  expect(screen.queryByRole("dialog")).toBeNull(); expect(trigger).toHaveFocus();
});

it("preserves last good content when a read fails and retries only the same GET", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(response(value())).mockRejectedValueOnce(new TypeError("synthetic network failure")).mockResolvedValueOnce(response(value()));
  vi.stubGlobal("fetch", fetcher); render(<Harness />); open();
  await screen.findByText("已核对：存储内容与本次引用一致。");
  fireEvent.click(screen.getByRole("button", { name: "重新读取已保存资料" }));
  await screen.findByRole("alert"); expect(screen.getByText(`已保存标题 ${A}`)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "重新读取已保存资料" }));
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(fetcher.mock.calls.every(call => call[0] === `/api/v1/analysis-runs/${R}/evidence/${A}` && (!call[1]?.method || call[1].method === "GET"))).toBe(true);
});

it("times out within the shared read deadline and restores retry without starting analysis", async () => {
  vi.useFakeTimers(); vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
  render(<Harness />); open();
  await act(async () => { await vi.advanceTimersByTimeAsync(15001); });
  expect(screen.getByRole("alert")).toHaveTextContent("读取引用资料超时");
  expect(screen.getByRole("button", { name: "重新读取已保存资料" })).toBeEnabled();
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("rejects wrong-run and malformed responses instead of adopting their contents", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(response({ ...value(), run_id: R2 })).mockResolvedValueOnce(response({ ...value(), status: "SNAPSHOT_ONLY", texts: [], citation: { source_locator: 123 } }));
  vi.stubGlobal("fetch", fetcher); render(<Harness />); open();
  expect(await screen.findByRole("alert")).toHaveTextContent("响应与当前运行或引用不一致");
  expect(screen.queryByText(`已保存标题 ${A}`)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "重新读取已保存资料" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  expect(screen.queryByText("123")).toBeNull();
});

it("discards a late response after close and run change, including fetch implementations ignoring abort", async () => {
  let resolve!: (input: unknown) => void;
  const fetcher = vi.fn().mockImplementationOnce(() => new Promise(done => { resolve = done; })).mockResolvedValueOnce(response(value(B, R2)));
  vi.stubGlobal("fetch", fetcher); const { rerender } = render(<Harness />); open();
  rerender(<Harness run={R2} />); open(B);
  await screen.findByText(`已保存标题 ${B}`);
  await act(async () => { resolve(response(value())); });
  expect(screen.queryByText(`已保存标题 ${A}`)).toBeNull(); expect(screen.getByText(`已保存标题 ${B}`)).toBeVisible();
});

it.each(["javascript:alert(1)", "data:text/html,bad", "file:///private", "https://user:password@source.example.test", "not a URL"])("never opens unsafe source locator %s", async locator => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ ...value(), citation: { ...value().citation, source_locator: locator } })));
  render(<Harness />); open(); await screen.findByText("已核对：存储内容与本次引用一致。");
  expect(screen.queryByRole("link")).toBeNull();
});

it("keeps historical missing evidence honest and supports Escape without network writes", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ ...value(), status: "NOT_RECORDED", citation: null, title: null, texts: [] })));
  render(<Harness />); open(); await screen.findByText(/此历史运行未记录可核对的输入快照/);
  const dialog = screen.getByRole("dialog"); fireEvent(dialog, new Event("cancel", { bubbles: true, cancelable: true }));
  expect(screen.queryByRole("dialog")).toBeNull(); expect(fetch).toHaveBeenCalledTimes(1);
});
