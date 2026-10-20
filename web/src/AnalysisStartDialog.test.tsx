import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnalysisStartDialog } from "./AnalysisStartDialog";
import { syntheticModelOptions } from "./testAnalysisModels";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const portfolio = { portfolio_id: "synthetic-portfolio", name: "合成组合", base_currency: "CNY" };
const noMarket = { configuration_hash: "b".repeat(64), profiles: [] };

describe("分析前确认", () => {
  it("requires an explicit portfolio choice for a watchlist target and never starts by itself", async () => {
    const onConfirm = vi.fn();
    const fetcher = vi.fn(async (url: string) => new Response(JSON.stringify(url === "/api/v1/analysis-market-options" ? noMarket : url === "/api/v1/analysis-model-options" ? syntheticModelOptions : [portfolio])));
    vi.stubGlobal("fetch", fetcher);
    render(<AnalysisStartDialog label="合成标的" onCancel={vi.fn()} onConfirm={onConfirm} />);
    expect(screen.getByRole("button", { name: "确认启动分析" })).toBeDisabled();
    expect(await screen.findByRole("option", { name: "合成组合 · CNY" })).toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByText(/可能调用付费模型/)).toBeVisible();
    fireEvent.change(screen.getByLabelText("分析所用组合"), { target: { value: portfolio.portfolio_id } });
    fireEvent.click(screen.getByRole("button", { name: "确认启动分析" }));
    expect(onConfirm).toHaveBeenCalledWith("synthetic-portfolio", { model_configuration_hash: "a".repeat(64), market_profile_ids: [] });
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual(expect.arrayContaining(["/api/v1/portfolios", "/api/v1/analysis-model-options", "/api/v1/analysis-market-options"]));
  });

  it("gives a creation link when no portfolio exists", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(url === "/api/v1/analysis-market-options" ? noMarket : url === "/api/v1/analysis-model-options" ? syntheticModelOptions : []))));
    render(<AnalysisStartDialog label="合成标的" onCancel={vi.fn()} onConfirm={vi.fn()} />);
    expect(await screen.findByRole("link", { name: "先创建一个组合 →" })).toHaveAttribute("href", "/portfolio");
    expect(screen.getByRole("button", { name: "确认启动分析" })).toBeDisabled();
  });

  it("blocks a failed portfolio read and keeps cancel usable", async () => {
    const onCancel = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("synthetic failure")));
    render(<AnalysisStartDialog label="合成标的" onCancel={onCancel} onConfirm={vi.fn()} />);
    expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent("无法连接本地服务");
    expect(screen.getByRole("button", { name: "确认启动分析" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "暂不分析" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("lets the user select one model without saving global settings and includes a confirmation hash", async () => {
    const onConfirm = vi.fn();
    const fetcher = vi.fn(async (url: string) => new Response(JSON.stringify(url === "/api/v1/analysis-market-options" ? noMarket : syntheticModelOptions)));
    vi.stubGlobal("fetch", fetcher);
    render(<AnalysisStartDialog label="合成标的" portfolio={portfolio} onCancel={vi.fn()} onConfirm={onConfirm} />);
    expect(await screen.findByRole("option", { name: /合成模型 · fixture-only/ })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("本次分析模型"), { target: { value: "synthetic-model" } });
    fireEvent.click(screen.getByText("核对本次模型与定价"));
    expect(screen.getByText(/全部八角色：合成模型/)).toHaveTextContent("synthetic-v1");
    fireEvent.click(screen.getByRole("button", { name: "确认启动分析" }));
    expect(onConfirm).toHaveBeenCalledWith(portfolio.portfolio_id, { model_profile_id: "synthetic-model", model_configuration_hash: "a".repeat(64), market_profile_ids: [] });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("blocks missing role mappings but allows an explicit complete single model choice", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(url === "/api/v1/analysis-market-options" ? noMarket : { ...syntheticModelOptions, default_bindings: [], missing_roles: ["RISK"] }))));
    render(<AnalysisStartDialog label="合成标的" portfolio={portfolio} onCancel={vi.fn()} onConfirm={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("尚未配置：风险经理");
    expect(screen.getByRole("button", { name: "确认启动分析" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("本次分析模型"), { target: { value: "synthetic-model" } });
    expect(screen.getByRole("button", { name: "确认启动分析" })).toBeEnabled();
  });

  it("recovers a model options failure by a read-only refresh and does not auto-confirm", async () => {
    const onConfirm = vi.fn();
    let modelReads = 0;
    const fetcher = vi.fn(async (url: string, _init?: RequestInit) => {
      if (url === "/api/v1/analysis-market-options") return new Response(JSON.stringify(noMarket));
      return ++modelReads === 1 ? new Response('{}', { status: 503 }) : new Response(JSON.stringify(syntheticModelOptions));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<AnalysisStartDialog label="合成标的" portfolio={portfolio} onCancel={vi.fn()} onConfirm={onConfirm} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 503");
    expect(screen.getByRole("button", { name: "确认启动分析" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "重新读取模型配置" }));
    await screen.findByRole("option", { name: /合成模型 · fixture-only/ });
    expect(screen.getByRole("button", { name: "确认启动分析" })).toBeEnabled();
    expect(onConfirm).not.toHaveBeenCalled();
    expect(fetcher.mock.calls.every(([, init]) => !init?.method)).toBe(true);
  });
});
