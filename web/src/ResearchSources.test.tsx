import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ResearchPage } from "./ResearchPage";

const target = { instrument_id: "synthetic-target", market: "SSE", symbol: "600011", name: "合成研究对象", asset_type: "EQUITY", currency: "CNY", sector: "" };
const profiles = Array.from({ length: 6 }, (_, index) => ({ id: `source-${index}`, name: `合成来源${index}`, provider_type: "BOCHA_WEB_SEARCH", enabled: true, credential_configured: true, retention_days: 365 }));
type Call = [string, RequestInit?];
function json(value: unknown) { return new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } }); }
function candidate(index: number) { return { candidate_id: `candidate-${index}`, source_name: `来源${index}`, source_locator: "https://synthetic.example.test/notice", source_tier: "OTHER", provider: `合成渠道${index}`, title: `合成资料${index}`, excerpt: "不可信合成文字", observed_at: "2026-10-23T00:00:00Z", available_at: "2026-10-23T01:00:00Z", expires_at: null, freshness_status: "FRESH" }; }
function preview(id: string, index: number, confirmed = false) { return { preview_id: id, profile_id: profiles[index].id, instrument_id: target.instrument_id, query: "合成公开查询", created_at: "2026-10-23T02:00:00Z", expires_at: "2026-10-23T02:10:00Z", as_of: "2026-10-23T02:00:00Z", candidates: [candidate(index)], confirmation: confirmed ? [{ candidate_id: `candidate-${index}`, evidence_id: `evidence-${index}`, reused: false }] : null }; }
function defaults(url: string): Response {
  if (url.endsWith("/settings/data-providers")) return json(profiles);
  if (url.endsWith("/research/capabilities")) return json({ provider_types: ["BOCHA_WEB_SEARCH"] });
  if (url.endsWith(`/instruments/${target.instrument_id}`)) return json(target);
  if (url.includes("/evidence?")) return json({ as_of: "2026-10-23T02:00:00Z", items: [] });
  throw new Error(`Unexpected read ${url}`);
}
async function chooseTwo() {
  await screen.findByRole("option", { name: "合成来源0 · BOCHA_WEB_SEARCH" });
  await screen.findByDisplayValue("合成研究对象 600011 最新公告");
  fireEvent.change(screen.getByLabelText("研究数据源"), { target: { value: profiles[0].id } });
  expect(screen.getByRole("checkbox", { name: "同时查询 合成来源1" })).not.toBeChecked();
  fireEvent.click(screen.getByRole("checkbox", { name: "同时查询 合成来源1" }));
  fireEvent.click(screen.getByRole("checkbox", { name: /我确认查询/ }));
}
beforeEach(() => { window.history.replaceState(null, "", `/research?instrument_id=${target.instrument_id}`); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState(null, "", "/"); });

describe("显式多来源研究预览", () => {
  it("queries only selected sources sequentially and merges independently confirmed evidence without overwriting", async () => {
    let release!: () => void;
    const calls: Call[] = [];
    const saved: number[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      calls.push([url, init]);
      if (init?.method === "POST" && url.endsWith("/preview")) {
        const request = JSON.parse(init.body as string);
        const index = url.includes("source-0") ? 0 : 1;
        return index === 0 ? new Promise<Response>((resolve) => { release = () => resolve(json(preview(request.request_id, 0))); }) : Promise.resolve(json(preview(request.request_id, 1)));
      }
      if (init?.method === "POST" && url.endsWith("/confirm")) {
        const index = JSON.parse(init.body as string).candidate_ids[0] === "candidate-0" ? 0 : 1;
        saved.push(index);
        return Promise.resolve(json([{ candidate_id: `candidate-${index}`, evidence_id: `evidence-${index}`, reused: false }]));
      }
      if (url.includes("/evidence?")) return Promise.resolve(json({ as_of: "2026-10-23T02:00:00Z", items: saved.map((index) => ({ ...candidate(index), evidence_id: `evidence-${index}`, evidence_type: "NEWS", ingested_at: "2026-10-23T02:00:00Z", content_hash: "synthetic" })) }));
      return Promise.resolve(defaults(url));
    }));
    render(<ResearchPage />);
    await chooseTwo();
    fireEvent.click(screen.getByRole("button", { name: "获取资料预览" }));
    fireEvent.click(screen.getByRole("button", { name: "正在获取预览…" }));
    expect(calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    expect(new URLSearchParams(window.location.search).getAll("preview_id")).toHaveLength(2);
    await act(async () => release());
    await screen.findByText(/已取得 2 条候选资料/);
    const queries = calls.filter(([url]) => url.endsWith("/preview"));
    expect(queries.map(([url]) => url)).toEqual(["/api/v1/research/providers/source-0/preview", "/api/v1/research/providers/source-1/preview"]);
    expect(queries.map(([, init]) => JSON.parse(init!.body as string).request_id)[0]).not.toBe(JSON.parse(queries[1][1]!.body as string).request_id);
    expect(screen.getByRole("checkbox", { name: "保存候选 合成资料0" })).not.toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: "保存候选 合成资料0" }));
    fireEvent.click(screen.getByRole("button", { name: "仅保存所选资料" }));
    await screen.findByRole("checkbox", { name: "用于本次分析 合成资料0" });
    fireEvent.click(screen.getAllByRole("button", { name: /查看此来源预览/ })[1]);
    expect(screen.getByRole("checkbox", { name: "保存候选 合成资料1" })).not.toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: "保存候选 合成资料1" }));
    fireEvent.click(screen.getByRole("button", { name: "仅保存所选资料" }));
    expect(await screen.findByRole("checkbox", { name: "用于本次分析 合成资料1" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "用于本次分析 合成资料0" })).toBeChecked();
    expect(screen.getByText(/本次已选 2 条证据/)).toBeVisible();
    expect(saved).toEqual([0, 1]);
    expect(calls.filter(([, init]) => init?.method === "POST")).toHaveLength(4);
    expect(calls.some(([url]) => url.includes("analysis-jobs"))).toBe(false);
  });

  it("retains success after a failed source, never calls unselected sources, and only GETs recovery", async () => {
    const calls: Call[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      calls.push([url, init]);
      if (url.endsWith("/preview")) {
        if (url.includes("source-0")) return Promise.reject(new Error("synthetic connection loss"));
        return Promise.resolve(json(preview(JSON.parse(init!.body as string).request_id, 1)));
      }
      if (url.includes("/previews/")) return Promise.resolve(new Response(JSON.stringify({ detail: "research_preview_not_found" }), { status: 404 }));
      return Promise.resolve(defaults(url));
    }));
    render(<ResearchPage />);
    await chooseTwo();
    fireEvent.click(screen.getByRole("button", { name: "获取资料预览" }));
    await screen.findByRole("checkbox", { name: "保存候选 合成资料1" });
    expect(screen.getByText(/成功结果仍保留/)).toBeVisible();
    expect(screen.getByText(/失败或结果未知；不等于未计费/)).toBeVisible();
    expect(calls.filter(([, init]) => init?.method === "POST")).toHaveLength(2);
    fireEvent.click(screen.getAllByRole("button", { name: "只读找回此来源" })[0]);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("没有找到原预览"));
    expect(calls.filter(([, init]) => init?.method === "POST")).toHaveLength(2);
    expect(screen.getByRole("checkbox", { name: "保存候选 合成资料1" })).not.toBeChecked();
  });

  it("restores all confirmed batches from URL using GET only and deduplicates evidence selection", async () => {
    window.history.replaceState(null, "", `/research?instrument_id=${target.instrument_id}&preview_id=preview-a&preview_id=preview-b`);
    const calls: Call[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      calls.push([url, init]);
      if (url.endsWith("/previews/preview-a")) return Promise.resolve(json(preview("preview-a", 0, true)));
      if (url.endsWith("/previews/preview-b")) return Promise.resolve(json(preview("preview-b", 1, true)));
      return Promise.resolve(defaults(url));
    }));
    render(<ResearchPage />);
    await screen.findByText(/本次已选 2 条证据/);
    fireEvent.click(screen.getAllByRole("button", { name: "只读找回此来源" })[0]);
    await screen.findByText("已读取原预览；没有再次查询供应商。");
    expect(screen.getByText(/本次已选 2 条证据/)).toBeVisible();
    expect(calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
    expect(screen.getByRole("checkbox", { name: /我确认查询/ })).not.toBeChecked();
  });

  it("does not start the next selected source after leaving the page", async () => {
    let release!: (value: Response) => void;
    const calls: Call[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      calls.push([url, init]);
      return init?.method === "POST" ? new Promise<Response>((resolve) => { release = resolve; }) : Promise.resolve(defaults(url));
    }));
    const view = render(<ResearchPage />);
    await chooseTwo();
    fireEvent.click(screen.getByRole("button", { name: "获取资料预览" }));
    const requestId = JSON.parse(calls.find(([, init]) => init?.method === "POST")![1]!.body as string).request_id;
    view.unmount();
    await act(async () => release(json(preview(requestId, 0))));
    expect(calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });

  it("limits source count and combined result count and revokes consent on plan changes", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(defaults(url))));
    render(<ResearchPage />);
    await chooseTwo();
    fireEvent.click(screen.getByRole("checkbox", { name: "同时查询 合成来源2" }));
    expect(screen.getByRole("checkbox", { name: /我确认查询/ })).not.toBeChecked();
    fireEvent.change(screen.getByLabelText("最多结果数"), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /我确认查询/ }));
    expect(screen.getByRole("button", { name: "获取资料预览" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("最多结果数"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "同时查询 合成来源3" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "同时查询 合成来源4" }));
    expect(screen.getByRole("checkbox", { name: "同时查询 合成来源5" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /我确认查询/ }));
    expect(screen.getByRole("button", { name: "获取资料预览" })).toBeEnabled();
  });

  it("rejects a returned preview for a different profile without showing its candidates", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => Promise.resolve(init?.method === "POST" ? json(preview(JSON.parse(init.body as string).request_id, 4)) : defaults(url))));
    render(<ResearchPage />);
    await chooseTwo();
    fireEvent.click(screen.getByRole("button", { name: "获取资料预览" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("返回预览与本次标的、来源或请求不一致"));
    expect(screen.queryByRole("checkbox", { name: "保存候选 合成资料4" })).not.toBeInTheDocument();
  });

  it("late recovery does not undo a user's cleared analysis selection", async () => {
    window.history.replaceState(null, "", `/research?instrument_id=${target.instrument_id}&preview_id=preview-a&preview_id=preview-b`);
    let release!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.endsWith("/previews/preview-a")) return Promise.resolve(json(preview("preview-a", 0, true)));
      if (url.endsWith("/previews/preview-b")) return new Promise<Response>((resolve) => { release = resolve; });
      return Promise.resolve(defaults(url));
    }));
    render(<ResearchPage />);
    await screen.findByText(/本次已选 1 条证据/);
    fireEvent.click(screen.getByRole("button", { name: "清空分析选择" }));
    await act(async () => release(json(preview("preview-b", 1, true))));
    expect(screen.getByText(/本次已选 0 条证据/)).toBeVisible();
    expect(screen.getAllByRole("button", { name: /查看此来源预览/ })).toHaveLength(2);
    expect(screen.getByRole("button", { name: "选择组合并分析" })).toBeDisabled();
  });

  it("a failed confirmation for one source retains the other saved selection and the current draft", async () => {
    window.history.replaceState(null, "", `/research?instrument_id=${target.instrument_id}&preview_id=preview-a&preview_id=preview-b`);
    const calls: Call[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      calls.push([url, init]);
      if (url.endsWith("/confirm")) return Promise.resolve(new Response(JSON.stringify({ detail: "research_preview_source_disabled" }), { status: 409 }));
      if (url.endsWith("/previews/preview-a")) return Promise.resolve(json(preview("preview-a", 0, true)));
      if (url.endsWith("/previews/preview-b")) return Promise.resolve(json(preview("preview-b", 1)));
      return Promise.resolve(defaults(url));
    }));
    render(<ResearchPage />);
    await screen.findByText(/本次已选 1 条证据/);
    await waitFor(() => expect(screen.getAllByRole("button", { name: /查看此来源预览/ })).toHaveLength(2));
    fireEvent.click(screen.getAllByRole("button", { name: /查看此来源预览/ })[1]);
    fireEvent.click(screen.getByRole("checkbox", { name: "保存候选 合成资料1" }));
    fireEvent.click(screen.getByRole("button", { name: "保存所选并继续分析" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("来源已停用"));
    expect(screen.getByRole("checkbox", { name: "保存候选 合成资料1" })).toBeChecked();
    expect(screen.getByText(/本次已选 1 条证据/)).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });

  it("late initial preview recovery revokes consent rather than authorizing a replaced query", async () => {
    window.history.replaceState(null, "", `/research?instrument_id=${target.instrument_id}&preview_id=preview-a`);
    let release!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn((url: string) => url.endsWith("/previews/preview-a") ? new Promise<Response>((resolve) => { release = resolve; }) : Promise.resolve(defaults(url))));
    render(<ResearchPage />);
    await screen.findByText(/当前标的/);
    fireEvent.click(screen.getByRole("checkbox", { name: /我确认查询/ }));
    await act(async () => release(json(preview("preview-a", 0))));
    expect(screen.getByLabelText("公开查询内容")).toHaveValue("合成公开查询");
    expect(screen.getByRole("checkbox", { name: /我确认查询/ })).not.toBeChecked();
    expect(screen.getByRole("button", { name: "获取资料预览" })).toBeDisabled();
  });
});
