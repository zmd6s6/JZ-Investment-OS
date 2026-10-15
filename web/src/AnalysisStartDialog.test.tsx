import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnalysisStartDialog } from "./AnalysisStartDialog";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const portfolio = { portfolio_id: "synthetic-portfolio", name: "合成组合", base_currency: "CNY" };

describe("分析前确认", () => {
  it("requires an explicit portfolio choice for a watchlist target and never starts by itself", async () => {
    const onConfirm = vi.fn();
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify([portfolio])));
    vi.stubGlobal("fetch", fetcher);
    render(<AnalysisStartDialog label="合成标的" onCancel={vi.fn()} onConfirm={onConfirm} />);
    expect(screen.getByRole("button", { name: "确认启动分析" })).toBeDisabled();
    expect(await screen.findByRole("option", { name: "合成组合 · CNY" })).toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByText(/可能调用付费模型/)).toBeVisible();
    fireEvent.change(screen.getByLabelText("分析所用组合"), { target: { value: portfolio.portfolio_id } });
    fireEvent.click(screen.getByRole("button", { name: "确认启动分析" }));
    expect(onConfirm).toHaveBeenCalledWith("synthetic-portfolio");
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][0]).toBe("/api/v1/portfolios");
  });

  it("gives a creation link when no portfolio exists", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('[]')));
    render(<AnalysisStartDialog label="合成标的" onCancel={vi.fn()} onConfirm={vi.fn()} />);
    expect(await screen.findByRole("link", { name: "先创建一个组合 →" })).toHaveAttribute("href", "/portfolio");
    expect(screen.getByRole("button", { name: "确认启动分析" })).toBeDisabled();
  });

  it("blocks a failed portfolio read and keeps cancel usable", async () => {
    const onCancel = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("synthetic failure")));
    render(<AnalysisStartDialog label="合成标的" onCancel={onCancel} onConfirm={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("无法连接本地服务");
    expect(screen.getByRole("button", { name: "确认启动分析" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "暂不分析" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
