import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnalysisPage } from "./AnalysisPage";
import { syntheticModelOptions } from "./testAnalysisModels";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const run = { id: "synthetic-run", instrument_id: "synthetic-instrument", portfolio_id: "synthetic-portfolio", source: "PORTFOLIO", status: "SUCCEEDED", created_at: "2026-10-15T00:00:00Z", as_of: "2026-10-15T00:00:00Z", policy_version_label: "TEST_DEFAULT", failure_code: null };
afterEach(() => { cleanup(); vi.useRealTimers(); sessionStorage.clear(); vi.unstubAllGlobals(); });

describe("分析读取反馈", () => {
  it("renders frozen model and pricing values without consulting current model settings", async () => {
    const fetcher = vi.fn(async (url: string) => {
      if (url.includes("?")) return json([run]);
      if (!url.startsWith("/api/v1/analysis-runs")) return json([]);
      return json({ ...run, payload: { input_snapshot: { evidence: [], model_plan: { mode: "ROLE_MAPPING", bindings: syntheticModelOptions.default_bindings } } } });
    });
    vi.stubGlobal("fetch", fetcher);
    render(<AnalysisPage />);
    fireEvent.click(await screen.findByRole("button", { name: "查看" }));
    fireEvent.click(await screen.findByText(/本次分析输入快照/));
    expect(screen.getByText("本次固定的模型与定价")).toBeVisible();
    expect(screen.getAllByText(/定价版本 synthetic-v1/)).toHaveLength(8);
    expect(fetcher.mock.calls.some(([url]) => url.includes("model-providers") || url.includes("model-options"))).toBe(false);
  });
  it("recovers a stalled detail read with an explicit read-only retry", async () => {
    vi.useFakeTimers();
    let stalled = true;
    const fetcher = vi.fn((url: string, init?: RequestInit) => {
      if (!url.startsWith("/api/v1/analysis-runs")) return Promise.resolve(json([]));
      if (url.includes("?")) return Promise.resolve(json([run]));
      return stalled ? new Promise<Response>(() => {}) : Promise.resolve(json({ ...run, payload: {} }));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<AnalysisPage />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    fireEvent.click(screen.getByRole("button", { name: "查看" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(15001); });
    expect(screen.getByRole("alert")).toHaveTextContent("读取分析记录超时");
    stalled = false;
    fireEvent.click(screen.getByRole("button", { name: "重试读取报告" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByRole("heading", { name: "分析详情 · 成功" })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetcher.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
  });
  it("makes the portfolio filter visible and can show all reports without a write", async () => {
    sessionStorage.setItem("selected_portfolio_id", "synthetic-portfolio");
    const fetcher = vi.fn().mockImplementation(async () => json([]));
    vi.stubGlobal("fetch", fetcher);
    render(<AnalysisPage />);
    const button = await screen.findByRole("button", { name: "查看全部组合报告" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith("/api/v1/analysis-runs?limit=50", expect.anything()));
    expect(screen.getByText(/范围：全部组合/)).toBeVisible();
    expect(fetcher.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
  });
  it("catches refresh errors and allows a successful retry", async () => {
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => !url.startsWith("/api/v1/analysis-runs") ? json([]) : ++reads === 1 ? json({ detail: "failure" }, 503) : json([run])));
    render(<AnalysisPage />);
    expect(await screen.findByText(/服务暂时无法完成请求/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "刷新运行列表" }));
    expect(await screen.findByRole("button", { name: "查看" })).toBeVisible();
    expect(screen.queryByText(/服务暂时无法完成请求/)).not.toBeInTheDocument();
  });

  it("shows detail progress, catches failure without dropping the list, and retries", async () => {
    let resolve!: (r: Response) => void;
    let details = 0;
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (!url.startsWith("/api/v1/analysis-runs")) return Promise.resolve(json([]));
      if (url.includes("?")) return Promise.resolve(json([run]));
      details++;
      if (details === 1) return new Promise<Response>((r) => { resolve = r; });
      return Promise.resolve(json({ ...run, payload: { failures: ["MISSING_REFERENCE_QUOTES"], opinions: [] } }));
    }));
    render(<AnalysisPage />);
    fireEvent.click(await screen.findByRole("button", { name: "查看" }));
    expect(await screen.findByRole("button", { name: "正在读取…" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "正在读取…" }));
    expect(details).toBe(1);
    await act(async () => resolve(json({}, 503)));
    expect(await screen.findByText(/服务暂时无法完成请求/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "查看" }));
    expect(await screen.findByText(/未配置可用行情或未获取到报价/)).toBeVisible();
    expect(screen.getByText(/没有 Tushare Token 不影响其他已配置功能/)).toBeVisible();
    expect(screen.getByText("此历史运行未记录本版输入快照，不追补或伪造。")).toBeVisible();
  });

  it("loads runs for the selected portfolio", async () => {
    sessionStorage.setItem("selected_portfolio_id", "synthetic-portfolio");
    const fetcher = vi.fn().mockResolvedValue(json([]));
    vi.stubGlobal("fetch", fetcher);
    render(<AnalysisPage />);
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith(expect.stringContaining("portfolio_id=synthetic-portfolio"), expect.anything()));
  });

  it("does not jump the page on background progress updates", async () => {
    const scroll = vi.fn();
    const previous = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = scroll;
    let details = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (!url.startsWith("/api/v1/analysis-runs")) return json([]);
      if (url.endsWith("/progress")) return json([]);
      if (url.includes("?")) return json([run]);
      return json({ ...run, payload: { execution_mode: "BACKGROUND", stage: ++details === 1 ? "ROUND_ONE" : "FINISHED" } });
    }));
    try {
      render(<AnalysisPage />);
      fireEvent.click(await screen.findByRole("button", { name: "查看" }));
      expect(await screen.findByText("当前阶段：任务结束")).toBeVisible();
      expect(details).toBe(2);
      expect(scroll).toHaveBeenCalledTimes(1);
    } finally { HTMLElement.prototype.scrollIntoView = previous; }
  });

  it("displays the stored input snapshot without looking up current evidence", async () => {
    const fetcher = vi.fn(async (url: string) => {
      if (!url.startsWith("/api/v1/analysis-runs")) return json([]);
      if (url.includes("?")) return json([run]);
      return json({ ...run, payload: { input_snapshot: { schema_version: "1.0", selection_mode: "EXPLICIT", as_of: run.as_of, policy_version_label: "TEST_DEFAULT", input_hash: "synthetic-input-hash", portfolio: { name: "运行当时的组合", base_currency: "CNY", cash_balance: "10000" }, evidence: [{ evidence_id: "frozen-evidence", content_hash: "frozen-hash", summary: "当时的材料", source_name: "合成来源", source_tier: "OTHER", provider: "合成渠道", source_locator: "javascript:alert(1)", observed_at: run.as_of, available_at: run.as_of, expires_at: null }] } } });
    });
    vi.stubGlobal("fetch", fetcher);
    const { container } = render(<AnalysisPage />);
    fireEvent.click(await screen.findByRole("button", { name: "查看" }));
    fireEvent.click(await screen.findByText("本次分析输入快照 · 1 条证据"));
    expect(screen.getByText(/运行当时的组合/)).toBeVisible();
    expect(screen.getByText(/frozen-evidence.*frozen-hash/)).toBeVisible();
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
    expect(fetcher.mock.calls.some(([url]) => url.includes("/evidence"))).toBe(false);
  });

  it("shows a veto even when no attempted BUY was blocked, and preserves full evidence references", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (!url.startsWith("/api/v1/analysis-runs")) return json([]);
      if (url.includes("?")) return json([run]);
      return json({ ...run, payload: { decision: { action: "WATCH", risk_veto: false }, risk: { gate: "VETO" }, opinions: [{ role: "RISK", claims: [{ claim: "合成风险事实", evidence_ids: ["synthetic-evidence"] }], unknowns: ["合成未知项"] }] } });
    }));
    render(<AnalysisPage />);
    fireEvent.click(await screen.findByRole("button", { name: "查看" }));
    expect(await screen.findByText("风险否决 是")).toBeVisible();
    expect(screen.queryByText("风险否决 否")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("完整观点 / 引用 / 未知项"));
    const citation = screen.getByText("synthetic-evidence");
    expect(citation).toBeVisible();
    expect(citation.closest(".muted")).toHaveTextContent("证据引用：synthetic-evidence");
    expect(screen.getByText("未知项：合成未知项")).toBeVisible();
  });
});
