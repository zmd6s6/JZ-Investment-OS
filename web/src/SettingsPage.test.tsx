import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SettingsPage } from "./SettingsPage";
import { setWriteToken } from "./writeApi";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const model = { id: "synthetic-model", name: "合成模型", enabled: true, credential_configured: true, provider_type: "OPENAI_COMPATIBLE", base_url: "https://model.example.invalid", model_name: "synthetic", timeout_seconds: 30, max_tokens: 1024 };
function mockSettings(write: (url: string, init: RequestInit) => Promise<Response>) {
  const fetcher = vi.fn((url: string, init?: RequestInit) => {
    if (init?.method && init.method !== "GET") return write(url, init);
    if (url.endsWith("/system")) return Promise.resolve(json({ market_timezone: "Asia/Shanghai", market_scopes: ["CN"], auto_trade: false }));
    if (url.endsWith("/model-providers")) return Promise.resolve(json([model]));
    if (url.endsWith("/llm-budget")) return Promise.resolve(json({ status: "NOT_CONFIGURED" }));
    return Promise.resolve(json([]));
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}
async function ready() { await waitFor(() => expect(screen.getByRole("button", { name: "保存系统设置" })).toBeEnabled()); }
afterEach(() => { cleanup(); sessionStorage.clear(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("设置操作反馈", () => {
  it("shows pending state, prevents duplicate writes, and sends authorization", async () => {
    let resolve!: (r: Response) => void;
    const pending = new Promise<Response>((r) => { resolve = r; });
    const fetcher = mockSettings(() => pending);
    setWriteToken("synthetic-write");
    render(<SettingsPage />); await ready();
    const button = screen.getByRole("button", { name: "保存系统设置" });
    fireEvent.click(button);
    expect(await screen.findByRole("button", { name: "正在保存…" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("正在保存系统设置");
    fireEvent.submit(button.closest("form")!);
    const writes = () => fetcher.mock.calls.filter(([, init]) => init?.method === "PUT");
    expect(writes()).toHaveLength(1);
    expect(new Headers(writes()[0][1]?.headers).get("Authorization")).toBe("Bearer synthetic-write");
    await act(async () => resolve(json({ market_timezone: "Asia/Shanghai", market_scopes: ["CN"], auto_trade: false })));
    expect(await screen.findByText("系统设置已保存；自动交易始终关闭。")).toBeVisible();
  });

  it("preserves data form inputs on 401 and explains the local token rather than encryption", async () => {
    mockSettings(async () => json({ detail: "write_api_unauthorized" }, 401));
    render(<SettingsPage />); await ready();
    const section = within(screen.getByRole("region", { name: "数据 / 研究提供方" }));
    fireEvent.change(section.getByLabelText("名称"), { target: { value: "合成数据档案" } });
    fireEvent.change(section.getByLabelText("基础 URL"), { target: { value: "https://data.example.invalid" } });
    fireEvent.click(section.getByRole("button", { name: "新增数据档案" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("尚未配置本系统的写入令牌");
    expect(section.getByLabelText("名称")).toHaveValue("合成数据档案");
    expect(section.getByLabelText("基础 URL")).toHaveValue("https://data.example.invalid");
    expect(section.getByRole("button", { name: "新增数据档案" })).toBeEnabled();
  });

  it("shows connection pending and a useful failed-test result", async () => {
    let resolve!: (r: Response) => void;
    mockSettings(() => new Promise((r) => { resolve = r; }));
    render(<SettingsPage />); await ready();
    fireEvent.click(screen.getByRole("button", { name: "测试模型连接" }));
    expect(await screen.findByRole("button", { name: "正在测试…" })).toBeDisabled();
    await act(async () => resolve(json({ status: "CREDENTIAL_MISSING", detail: "synthetic diagnostic", latency_ms: null })));
    expect(await screen.findByRole("alert")).toHaveTextContent("未配置此提供方的 API Key");
    expect(screen.getByRole("button", { name: "测试模型连接" })).toBeEnabled();
  });

  it("clearing a role mapping sends the local bearer and confirms completion", async () => {
    const fetcher = mockSettings(async () => new Response(null, { status: 204 }));
    setWriteToken("synthetic-write");
    render(<SettingsPage />); await ready();
    fireEvent.change(screen.getByLabelText("MACRO 模型"), { target: { value: "" } });
    await waitFor(() => expect(fetcher.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(true));
    const call = fetcher.mock.calls.find(([, init]) => init?.method === "DELETE")!;
    expect(new Headers(call[1]?.headers).get("Authorization")).toBe("Bearer synthetic-write");
  });
});
