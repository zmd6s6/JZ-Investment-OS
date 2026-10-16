import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LocalAccessBoundary } from "./LocalAccess";
import { ProductChrome } from "./ProductChrome";
import { getWriteToken, setApiAuthMode, setWriteToken } from "./writeApi";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
afterEach(() => { cleanup(); sessionStorage.clear(); window.history.replaceState({}, "", "/"); setApiAuthMode("bearer"); vi.unstubAllGlobals(); });

describe("本机无感会话", () => {
  it("blocks private pages before pairing and offers the launcher instead of a token input", async () => {
    const fetcher = vi.fn().mockResolvedValue(json({ mode: "local_session", authenticated: false, expires_at: null }));
    vi.stubGlobal("fetch", fetcher);
    render(<LocalAccessBoundary><div>私有业务页面</div></LocalAccessBoundary>);
    expect(await screen.findByText("从本地入口打开，即可开始")).toBeVisible();
    expect(screen.queryByText("私有业务页面")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("写入令牌")).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][0]).toBe("/api/v1/auth/session");
  });

  it("clears the bootstrap fragment before exchange and redeems only once under StrictMode", async () => {
    window.history.replaceState({}, "", "/#local-pair=synthetic-pairing-code");
    setWriteToken("synthetic-old-bearer");
    const fetcher = vi.fn(async (url: string) => {
      expect(window.location.hash).toBe("");
      return json(url.endsWith("/pair") ? {} : { mode: "local_session", authenticated: true, expires_at: 9999999999 });
    });
    vi.stubGlobal("fetch", fetcher);
    render(<StrictMode><LocalAccessBoundary><ProductChrome eyebrow="测试" title="合成页面">私有内容</ProductChrome></LocalAccessBoundary></StrictMode>);
    expect(await screen.findByRole("button", { name: "本机已连接" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "配置写令牌" })).not.toBeInTheDocument();
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith("/pair"))).toHaveLength(1);
    expect(getWriteToken()).toBe("");
  });

  it("keeps business pages gated after an invalid bootstrap code", async () => {
    window.history.replaceState({}, "", "/#local-pair=synthetic-invalid-code");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({}, 401)));
    render(<LocalAccessBoundary><div>私有业务页面</div></LocalAccessBoundary>);
    expect(await screen.findByRole("alert")).toHaveTextContent("链接已失效或已使用");
    expect(window.location.hash).toBe("");
    expect(screen.queryByText("私有业务页面")).not.toBeInTheDocument();
  });

  it("revokes the session without deleting business records or requesting a provider", async () => {
    const fetcher = vi.fn(async (url: string) => url.endsWith("/logout") ? new Response(null, { status: 204 }) : json({ mode: "local_session", authenticated: true, expires_at: 9999999999 }));
    vi.stubGlobal("fetch", fetcher);
    render(<LocalAccessBoundary><ProductChrome eyebrow="测试" title="合成页面">私有内容</ProductChrome></LocalAccessBoundary>);
    fireEvent.click(await screen.findByRole("button", { name: "本机已连接" }));
    fireEvent.click(screen.getByRole("button", { name: "断开本机访问" }));
    expect(await screen.findByText("从本地入口打开，即可开始")).toBeVisible();
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[1][0]).toBe("/api/v1/auth/logout");
  });

  it("responds to expiry without exposing manual tokens or silently replaying a write", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ mode: "local_session", authenticated: true, expires_at: 9999999999 })));
    render(<LocalAccessBoundary><div>私有业务页面</div></LocalAccessBoundary>);
    await screen.findByText("私有业务页面");
    fireEvent(window, new Event("investment-os:session-expired"));
    await waitFor(() => expect(screen.queryByText("私有业务页面")).not.toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("重新从本地启动入口打开");
  });
});
