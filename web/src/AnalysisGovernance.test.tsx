import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AnalysisGovernance } from "./AnalysisGovernance";
import { PolicyReviewPanel } from "./PolicyReviewPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear(); });
const hash = "a".repeat(64);

it("shows fixed policy and prompt provenance without consulting current settings", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<AnalysisGovernance value={{ policy: { mode: "ACTIVE", policy_version_id: "synthetic-v1", version: 1, content_hash: hash, config: { metadata: { name: "当时的政策" }, position: { single_instrument_max_pct: "2" } } }, formula: { version: "frozen-test-formula", status: "TEST_DEFAULT" }, prompts: [{ role: "MACRO", version: "frozen-prompt-v1", content_hash: hash }] }} />);
  fireEvent.click(screen.getByText("政策与运行规则版本 · 只读快照"));
  expect(screen.getByText("政策：当时的政策@1")).toBeVisible();
  expect(screen.getByText("单标的上限（%）：2")).toBeVisible();
  expect(screen.getByText("宏观 · frozen-prompt-v1")).toBeVisible();
  expect(screen.getByText(/当前公式仍是 TEST_DEFAULT/)).toBeVisible();
  expect(fetcher).not.toHaveBeenCalled();
});

it("never backfills an old report with current policy metadata", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<AnalysisGovernance value={undefined} />);
  expect(screen.getByText(/不记录|未记录完整政策/)).toBeVisible();
  expect(fetcher).not.toHaveBeenCalled();
});

it("reads the selected portfolio policy with precise labels and only issues GETs", async () => {
  sessionStorage.setItem("selected_portfolio_id", "synthetic-portfolio");
  const fetcher = vi.fn(async (_url: string) => new Response(JSON.stringify({ active_policy_version: "TEST_DEFAULT", policy_status: "TEST_DEFAULT", is_test_default: true, limits: [{ key: "single_instrument_max_pct", value: "8" }], snapshot: { content_hash: hash }, warning: "工程测试值，不是真实投资限额" })));
  vi.stubGlobal("fetch", fetcher);
  render(<PolicyReviewPanel />);
  expect(await screen.findByText("单标的上限（%）")).toBeVisible();
  expect(screen.getByText(/无真实批准版本/)).toBeVisible();
  expect(fetcher.mock.calls[0][0]).toBe("/api/v1/policy/review?portfolio_id=synthetic-portfolio");
  fireEvent.click(screen.getByRole("checkbox"));
  expect(screen.getByText(/本地界面状态，不改政策/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "重新读取政策" }));
  expect(await screen.findByText("单标的上限（%）")).toBeVisible();
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("rejects malformed policy reads and allows retry without modifying policy", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(new Response("{}")).mockResolvedValueOnce(new Response(JSON.stringify({ active_policy_version: "unavailable", policy_status: "INVALID", is_test_default: false, limits: [], warning: "批准不完整，未自动切换政策" })));
  vi.stubGlobal("fetch", fetcher);
  render(<PolicyReviewPanel />);
  expect(await screen.findByText(/政策响应不完整/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "重新读取政策" }));
  expect(await screen.findByText("批准不完整，未自动切换政策")).toBeVisible();
  expect(screen.getByTestId("policy-status")).toHaveTextContent("INVALID");
  expect(fetcher.mock.calls.every(([, options]) => !options?.method)).toBe(true);
});
