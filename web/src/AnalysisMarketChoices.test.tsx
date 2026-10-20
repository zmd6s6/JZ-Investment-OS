import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnalysisMarketChoices } from "./AnalysisMarketChoices";
import { AnalysisMarketAudit, DurableMarketAudit } from "./AnalysisMarketAudit";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const hash = "b".repeat(64);
const profiles = ["主行情", "备行情", "未选源"].map((name, index) => ({ profile_id: `synthetic-${index}`, name, provider_type: "TUSHARE_MARKET" }));

describe("本次行情选择", () => {
  it("defaults to no sources, preserves explicit order, supports reorder and clear without a write", async () => {
    const fetcher = vi.fn(async (_url: string) => new Response(JSON.stringify({ configuration_hash: hash, profiles })));
    vi.stubGlobal("fetch", fetcher);
    const changed = vi.fn();
    render(<AnalysisMarketChoices onChange={changed} />);
    const one = await screen.findByRole("checkbox", { name: /主行情/ });
    expect(one).not.toBeChecked();
    expect(changed).toHaveBeenLastCalledWith({ market_profile_ids: [] });
    fireEvent.click(screen.getByRole("checkbox", { name: /备行情/ }));
    fireEvent.click(one);
    expect(changed).toHaveBeenLastCalledWith({ market_profile_ids: ["synthetic-1", "synthetic-0"], market_configuration_hash: hash });
    fireEvent.click(screen.getByRole("button", { name: "上移 主行情" }));
    expect(changed).toHaveBeenLastCalledWith({ market_profile_ids: ["synthetic-0", "synthetic-1"], market_configuration_hash: hash });
    expect(screen.getByRole("checkbox", { name: /未选源/ })).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "清空行情选择" }));
    expect(changed).toHaveBeenLastCalledWith({ market_profile_ids: [] });
    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher.mock.calls[0][0]).toBe("/api/v1/analysis-market-options");
  });

  it("refresh clears the previous confirmation; malformed options fail visibly without selecting any provider", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ configuration_hash: hash, profiles }))).mockResolvedValueOnce(new Response('{}'));
    vi.stubGlobal("fetch", fetcher);
    const changed = vi.fn();
    render(<AnalysisMarketChoices onChange={changed} />);
    fireEvent.click(await screen.findByRole("checkbox", { name: /主行情/ }));
    fireEvent.click(screen.getByRole("button", { name: "重新读取行情配置" }));
    expect(await screen.findByText(/行情配置响应不完整/)).toBeVisible();
    expect(changed).toHaveBeenLastCalledWith({ market_profile_ids: [] });
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("limits a single run to ten sources", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ configuration_hash: hash, profiles: Array.from({ length: 11 }, (_, index) => ({ profile_id: String(index), name: `源${index}`, provider_type: "TUSHARE_MARKET" })) }))));
    render(<AnalysisMarketChoices onChange={vi.fn()} />);
    await screen.findByRole("checkbox", { name: /源10/ });
    const boxes = screen.getAllByRole("checkbox");
    for (const box of boxes.slice(0, 10)) fireEvent.click(box);
    expect(boxes[10]).toBeDisabled();
    fireEvent.click(boxes[0]);
    expect(boxes[10]).toBeEnabled();
  });

  it("reports a bounded read failure and allows an explicit read-only retry", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("synthetic offline"); }));
    render(<AnalysisMarketChoices onChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(/可不读取行情继续/)).toBeVisible());
    expect(screen.getByRole("button", { name: "重新读取行情配置" })).toBeEnabled();
  });
});

describe("历史行情审计", () => {
  it("reads durable unknown intent after cancellation and only retries a GET", async () => {
    const event = { attempt_id: "attempt", occurred_at: "2026-10-20T08:00:00Z", attempt: { profile_id: "a", name: "固定主源", provider_type: "TUSHARE_MARKET", rank: 0, status: "STARTED", queries: ["SSE:600519"] } };
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify([event]))).mockResolvedValueOnce(new Response("{}", { status: 503 }));
    vi.stubGlobal("fetch", fetcher);
    render(<DurableMarketAudit runId="cancelled" active={false} tracked fallback={undefined} />);
    expect(await screen.findByText(/结果未知；可能未发出/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "重新读取行情记录" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("不会重发行情或模型请求");
    expect(screen.getByText("第 1 档 · 固定主源")).toBeVisible();
    expect(fetcher.mock.calls.every(([url, init]) => url === "/api/v1/analysis-runs/cancelled/market-attempts" && !init?.method)).toBe(true);
  });

  it("pairs a completed result with its start and does not fetch legacy history", async () => {
    const attempt = { profile_id: "a", name: "固定来源", rank: 0, queries: [] };
    const fetcher = vi.fn(async () => new Response(JSON.stringify([
      { attempt_id: "one", occurred_at: "start", attempt: { ...attempt, status: "STARTED" } },
      { attempt_id: "one", occurred_at: "end", attempt: { ...attempt, status: "NO_DATA" } },
    ])));
    vi.stubGlobal("fetch", fetcher);
    const view = render(<DurableMarketAudit runId="finished" active={false} tracked fallback={undefined} />);
    expect(await screen.findByText(/未取得可用报价；查询/)).toBeVisible();
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.queryByText(/结果未知；可能未发出/)).not.toBeInTheDocument();
    view.unmount();
    render(<DurableMarketAudit runId="legacy" active={false} tracked={false} fallback={undefined} />);
    expect(screen.getByText(/不根据当前设置追补/)).toBeVisible();
    expect(fetcher).toHaveBeenCalledOnce();
  });
  it("shows frozen order, precise price, timestamps and failures without looking up current settings", () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    render(<AnalysisMarketAudit value={{ selection: "ORDERED", attempts: [
      { profile_id: "a", name: "当时主源", provider_type: "TUSHARE_MARKET", rank: 0, status: "NO_DATA", queries: ["SSE:600519"] },
      { profile_id: "b", name: "当时备源", provider_type: "TUSHARE_MARKET", rank: 1, status: "SUCCEEDED", queries: ["SSE:600519"], quotes: [{ instrument_id: "synthetic", reference_price: "12.34567890123456789", currency: "CNY", as_of: "2026-10-20T07:00:00Z" }] },
    ] }} />);
    fireEvent.click(screen.getByText("行情来源实际尝试 · 2 项"));
    const rows = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("当时主源");
    expect(rows[1]).toHaveTextContent("12.34567890123456789 CNY");
    expect(rows[1]).toHaveTextContent("2026-10-20T07:00:00Z");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("distinguishes no selection from legacy unrecorded history", () => {
    const view = render(<AnalysisMarketAudit value={undefined} />);
    expect(screen.getByText(/不根据当前设置追补/)).toBeVisible();
    view.rerender(<AnalysisMarketAudit value={{ selection: "NONE", attempts: [] }} />);
    expect(screen.getByText(/没有自动调用已启用来源/)).toBeVisible();
  });
});
