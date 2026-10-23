import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WatchlistPage } from "./WatchlistPage";
import { setWriteToken } from "./writeApi";
import { syntheticModelOptions } from "./testAnalysisModels";

afterEach(() => { cleanup(); sessionStorage.clear(); vi.unstubAllGlobals(); });
const item = { watchlist_item_id: "synthetic-watch", instrument_id: "synthetic-instrument", symbol: "600000", market: "SSE", name: "合成观察标的" };
const portfolio = { portfolio_id: "synthetic-portfolio", name: "合成上下文", base_currency: "CNY" };

describe("观察清单研究入口", () => {
  it("confirms context before calling analysis and preserves the watchlist on failure", async () => {
    const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/analysis-model-options") return new Response(JSON.stringify(syntheticModelOptions));
      if (url === "/api/v1/watchlist") return new Response(JSON.stringify([item]));
      if (url === "/api/v1/portfolios") return new Response(JSON.stringify([portfolio]));
      if (init?.method === "POST") return new Response('{}', { status: 503 });
      return new Response('[]');
    });
    vi.stubGlobal("fetch", fetcher); setWriteToken("synthetic-access");
    render(<WatchlistPage />);
    fireEvent.click(await screen.findByRole("button", { name: "立即分析" }));
    expect(await screen.findByRole("option", { name: "合成上下文 · CNY" })).toBeInTheDocument();
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
    fireEvent.change(screen.getByLabelText("分析所用组合"), { target: { value: "synthetic-portfolio" } });
    fireEvent.click(screen.getByRole("button", { name: "确认启动分析" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("服务暂时无法完成请求");
    const call = fetcher.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(call[0]).toBe("/api/v1/analysis-jobs");
    expect(JSON.parse(String(call[1]?.body))).toMatchObject({ instrument_id: "synthetic-instrument", portfolio_id: "synthetic-portfolio", source: "WATCHLIST" });
    expect(new Headers(call[1]?.headers).get("Authorization")).toBe("Bearer synthetic-access");
    expect(screen.getByRole("cell", { name: "合成观察标的" })).toBeVisible();
    await waitFor(() => expect(screen.getByRole("button", { name: "立即分析" })).toBeEnabled());
  });
});
