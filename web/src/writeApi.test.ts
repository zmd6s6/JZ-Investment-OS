import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetch, getWriteToken, readApiError, setWriteToken, verifyWriteToken } from "./writeApi";

afterEach(() => { sessionStorage.clear(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const response = (status: number, detail: unknown) => new Response(JSON.stringify({ detail }), { status });

describe("统一请求与安全错误提示", () => {
  it("writes carry the session bearer, reads do not, explicit verification uses the candidate", async () => {
    setWriteToken("synthetic-old");
    const fetcher = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetcher);
    await apiFetch("/api/v1/settings/system", { method: "PUT" });
    expect(new Headers(fetcher.mock.calls[0][1].headers).get("Authorization")).toBe("Bearer synthetic-old");
    await apiFetch("/api/v1/settings/system");
    expect(new Headers(fetcher.mock.calls[1][1].headers).has("Authorization")).toBe(false);
    await verifyWriteToken("synthetic-new");
    expect(new Headers(fetcher.mock.calls[2][1].headers).get("Authorization")).toBe("Bearer synthetic-new");
    expect(getWriteToken()).toBe("synthetic-old");
  });

  it("distinguishes missing local authorization from invalid authorization", async () => {
    expect(await readApiError(response(401, "write_api_unauthorized"))).toContain("尚未配置");
    setWriteToken("synthetic-old");
    expect(await readApiError(response(401, "write_api_unauthorized"))).toContain("不正确或已失效");
    expect(await readApiError(response(503, "write_api_token_not_configured"))).toContain("服务端尚未配置");
  });

  it("shows field names without leaking rejected credential values", async () => {
    const text = await readApiError(response(422, [{ loc: ["body", "base_url"], input: "synthetic-private-input", msg: "invalid" }]));
    expect(text).toContain("基础 URL");
    expect(text).not.toContain("synthetic-private-input");
    expect(await readApiError(response(500, "synthetic-private-server-detail"))).not.toContain("synthetic-private-server-detail");
  });

  it("handles proxy and network failures without suggesting key rotation", async () => {
    expect(await readApiError(new Response("<html>bad gateway</html>", { status: 504 }))).toContain("结果尚未确认");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("synthetic-private-network-detail")));
    await expect(apiFetch("/api/v1/settings/system")).rejects.toThrow("无法连接本地服务");
  });

  it("rejects incorrect and empty candidate tokens without saving them", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(401, "write_api_unauthorized")));
    await expect(verifyWriteToken("synthetic-bad")).rejects.toThrow("写入令牌不正确");
    await expect(verifyWriteToken(" ")).rejects.toThrow("请输入");
    expect(getWriteToken()).toBe("");
  });
});
