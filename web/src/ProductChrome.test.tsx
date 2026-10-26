import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProductChrome, StatusBanner } from "./ProductChrome";
import { getWriteToken } from "./writeApi";

afterEach(() => { cleanup(); sessionStorage.clear(); vi.unstubAllGlobals(); });
describe("本地访问验证", () => {
  it("focuses a full dialog, allows typing and reveal, and cancels without a request", () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    render(<ProductChrome eyebrow="测试" title="测试">合成页面</ProductChrome>);
    fireEvent.click(screen.getByRole("button", { name: "配置写令牌" }));
    expect(screen.getByRole("dialog", { name: "配置本地访问" })).toBeVisible();
    const input = screen.getByLabelText("写入令牌");
    expect(input).toHaveFocus();
    fireEvent.change(input, { target: { value: "synthetic-local-access" } });
    fireEvent.click(screen.getByRole("button", { name: "显示" }));
    expect(input).toHaveAttribute("type", "text");
    expect(input).toHaveValue("synthetic-local-access");
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
    expect(getWriteToken()).toBe("");
  });

  it("explains an empty token without sending a request", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    render(<ProductChrome eyebrow="测试" title="测试">合成页面</ProductChrome>);
    fireEvent.click(screen.getByRole("button", { name: "配置写令牌" }));
    fireEvent.click(screen.getByRole("button", { name: "验证并保存令牌" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("请输入");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("offers an authorization repair action without replaying the failed write", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{}'));
    vi.stubGlobal("fetch", fetcher);
    render(<ProductChrome eyebrow="测试" title="测试"><StatusBanner kind="error" text="尚未配置本系统的写入令牌" /></ProductChrome>);
    fireEvent.click(screen.getByRole("button", { name: "配置本地访问 →" }));
    fireEvent.change(screen.getByLabelText("写入令牌"), { target: { value: "synthetic-local-access" } });
    fireEvent.click(screen.getByRole("button", { name: "验证并保存令牌" }));
    expect(await screen.findByText(/请重新点击刚才的保存操作/)).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][0]).toBe("/api/v1/auth/check");
  });

  it("saves only after successful verification and explains the credential boundary", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{"status":"authorized"}'));
    vi.stubGlobal("fetch", fetcher);
    render(<ProductChrome eyebrow="测试" title="测试">合成页面</ProductChrome>);
    fireEvent.click(screen.getByRole("button", { name: "配置写令牌" }));
    fireEvent.change(screen.getByLabelText("写入令牌"), { target: { value: "synthetic-local-access" } });
    fireEvent.click(screen.getByRole("button", { name: "验证并保存令牌" }));
    expect(await screen.findByRole("button", { name: "本地访问已验证" })).toBeVisible();
    expect(getWriteToken()).toBe("synthetic-local-access");
    expect(fetcher).toHaveBeenCalledWith("/api/v1/auth/check", expect.objectContaining({ method: "POST" }));
  });

  it("keeps the dialog open and does not store a rejected token", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"detail":"write_api_unauthorized"}', { status: 401 })));
    render(<ProductChrome eyebrow="测试" title="测试">合成页面</ProductChrome>);
    fireEvent.click(screen.getByRole("button", { name: "配置写令牌" }));
    fireEvent.change(screen.getByLabelText("写入令牌"), { target: { value: "synthetic-invalid" } });
    fireEvent.click(screen.getByRole("button", { name: "验证并保存令牌" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("写入令牌不正确");
    await waitFor(() => expect(screen.getByRole("button", { name: "验证并保存令牌" })).toBeEnabled());
    expect(getWriteToken()).toBe("");
  });
});
