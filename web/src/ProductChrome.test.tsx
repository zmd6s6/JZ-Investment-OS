import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProductChrome } from "./ProductChrome";
import { getWriteToken } from "./writeApi";

afterEach(() => { cleanup(); sessionStorage.clear(); vi.unstubAllGlobals(); });
describe("本地访问验证", () => {
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
