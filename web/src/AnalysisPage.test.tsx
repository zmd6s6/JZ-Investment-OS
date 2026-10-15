import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnalysisPage } from "./AnalysisPage";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const run = { id: "synthetic-run", instrument_id: "synthetic-instrument", portfolio_id: "synthetic-portfolio", source: "PORTFOLIO", status: "SUCCEEDED", created_at: "2026-10-15T00:00:00Z", as_of: "2026-10-15T00:00:00Z", policy_version_label: "TEST_DEFAULT", failure_code: null };
afterEach(() => { cleanup(); sessionStorage.clear(); vi.unstubAllGlobals(); });

describe("分析读取反馈", () => {
  it("catches refresh errors and allows a successful retry", async () => {
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn(async () => ++reads === 1 ? json({ detail: "failure" }, 503) : json([run])));
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
  });

  it("loads runs for the selected portfolio", async () => {
    sessionStorage.setItem("selected_portfolio_id", "synthetic-portfolio");
    const fetcher = vi.fn().mockResolvedValue(json([]));
    vi.stubGlobal("fetch", fetcher);
    render(<AnalysisPage />);
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith(expect.stringContaining("portfolio_id=synthetic-portfolio"), expect.anything()));
  });
});
