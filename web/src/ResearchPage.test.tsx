import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ResearchPage } from "./ResearchPage";
import { syntheticModelOptions } from "./testAnalysisModels";

const a = { instrument_id: "synthetic-a", market: "SSE", symbol: "600011", name: "合成甲", asset_type: "EQUITY", currency: "CNY", sector: "" };
const b = { ...a, instrument_id: "synthetic-b", name: "合成乙", symbol: "600012" };
const profile = { id: "synthetic-provider", name: "合成研究源", provider_type: "BOCHA_WEB_SEARCH", enabled: true, credential_configured: true, retention_days: 365 };
const evidence = { evidence_id: "synthetic-evidence", source_name: "合成来源", source_locator: "javascript:alert(1)", source_tier: "OTHER", provider: "合成研究源", evidence_type: "NEWS", title: "合成公告", excerpt: "<script>alert(1)</script>仅为不可信文字", observed_at: "2026-10-15T00:00:00Z", available_at: "2026-10-15T01:00:00Z", ingested_at: "2026-10-15T01:00:01Z", expires_at: null, freshness_status: "FRESH", content_hash: "synthetic-hash" };
const draft = { preview_id: "synthetic-preview", profile_id: profile.id, instrument_id: a.instrument_id, query: "合成公开查询", created_at: "2026-10-15T02:00:00Z", expires_at: "2026-10-15T02:10:00Z", as_of: "2026-10-15T02:00:00Z", candidates: [{ ...evidence, candidate_id: "candidate-one" }, { ...evidence, title: "不选的公告", candidate_id: "candidate-two" }], confirmation: null };
vi.mock("./InstrumentSearchBox", () => ({ InstrumentSearchBox: ({ onSelect }: { onSelect: (hit: typeof a) => void }) => <div><button onClick={() => onSelect(a)}>选择甲</button><button onClick={() => onSelect(b)}>选择乙</button></div> }));
function json(value: unknown) { return new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } }); }
function defaults(url: string) {
  if (url === "/api/v1/analysis-model-options") return json(syntheticModelOptions);
  if (url === "/api/v1/settings/data-providers") return json([profile]);
  if (url === "/api/v1/research/capabilities") return json({ provider_types: ["BOCHA_WEB_SEARCH"] });
  if (url === "/api/v1/instruments/synthetic-a") return json(a);
  if (url.includes("/evidence?")) return json({ as_of: "2026-10-15T02:00:00Z", items: [] });
  if (url === "/api/v1/portfolios") return json([{ portfolio_id: "synthetic-portfolio", name: "合成组合", base_currency: "CNY" }]);
  throw new Error(`unexpected ${url}`);
}
beforeEach(() => { window.history.replaceState(null, "", "/research?instrument_id=synthetic-a"); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState(null, "", "/"); });

describe("页面化研究资料", () => {
  it("previews before saving, only confirms selected IDs, prevents double calls and leaves models untouched", async () => {
    let release!: (value: Response) => void;
    let saved = false;
    const fetcher = vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "POST" && url.endsWith("/confirm")) {
        saved = true;
        return Promise.resolve(json([{ candidate_id: "candidate-one", evidence_id: evidence.evidence_id, reused: false }]));
      }
      if (init?.method === "POST") return new Promise<Response>((resolve) => { release = resolve; });
      if (url.includes("/evidence?") && saved) return Promise.resolve(json({ as_of: "2026-10-15T02:00:00Z", items: [evidence] }));
      return Promise.resolve(defaults(url));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<ResearchPage />);
    await screen.findByRole("option", { name: "合成研究源 · BOCHA_WEB_SEARCH" });
    await screen.findByText("这个标的还没有已存资料");
    const submit = screen.getByRole("button", { name: "获取资料预览" });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText("研究数据源"), { target: { value: profile.id } });
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /我确认查询/ }));
    fireEvent.change(screen.getByLabelText("公开查询内容"), { target: { value: "合成公开查询" } });
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /我确认查询/ }));
    fireEvent.click(submit); fireEvent.click(submit);
    expect(screen.getByRole("button", { name: "正在获取预览…" })).toBeDisabled();
    const posts = fetcher.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(posts).toHaveLength(1);
    expect(posts[0][0]).toBe(`/api/v1/research/providers/${profile.id}/preview`);
    expect(JSON.parse(posts[0][1]!.body as string)).toMatchObject({ query: "合成公开查询", instrument_id: a.instrument_id, max_results: 5 });
    await act(async () => release(json({ ...draft, preview_id: JSON.parse(posts[0][1]!.body as string).request_id })));
    expect(await screen.findByRole("checkbox", { name: "保存候选 合成公告" })).not.toBeChecked();
    expect(screen.getByRole("button", { name: "仅保存所选资料" })).toBeDisabled();
    expect(screen.getByText("这个标的还没有已存资料")).toBeVisible();
    fireEvent.click(screen.getByRole("checkbox", { name: "保存候选 合成公告" }));
    fireEvent.click(screen.getByRole("button", { name: "仅保存所选资料" }));
    expect(await screen.findByRole("checkbox", { name: "用于本次分析 合成公告" })).toBeChecked();
    const confirmation = fetcher.mock.calls.find(([url]) => url.endsWith("/confirm"));
    expect(JSON.parse(confirmation![1]!.body as string)).toEqual({ instrument_id: a.instrument_id, candidate_ids: ["candidate-one"] });
    expect(fetcher.mock.calls.some(([url]) => url.includes("analysis-runs"))).toBe(false);
    expect(screen.getByRole("button", { name: "获取资料预览" })).toBeDisabled();
  });

  it("explains unsupported and disabled sources without requiring a Tushare token", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(url === "/api/v1/settings/data-providers" ? json([{ ...profile, enabled: false }, { ...profile, id: "market", name: "行情档案", provider_type: "TUSHARE_MARKET" }]) : defaults(url))));
    render(<ResearchPage />);
    expect(await screen.findByRole("option", { name: /行情档案.*不支持研究检索/ })).toBeDisabled();
    expect(screen.getByRole("option", { name: /合成研究源.*未启用/ })).toBeDisabled();
    expect(screen.getByText(/尚无可用研究来源/)).toBeVisible();
    expect(screen.getByRole("button", { name: "获取资料预览" })).toBeDisabled();
  });

  it("keeps input and has no automatic fallback after provider failure", async () => {
    const fetcher = vi.fn((url: string, init?: RequestInit) => Promise.resolve(init?.method === "POST" ? new Response(JSON.stringify({ detail: "research_provider_unavailable" }), { status: 502 }) : defaults(url)));
    vi.stubGlobal("fetch", fetcher);
    render(<ResearchPage />);
    await screen.findByRole("option", { name: "合成研究源 · BOCHA_WEB_SEARCH" });
    fireEvent.change(screen.getByLabelText("研究数据源"), { target: { value: profile.id } });
    fireEvent.click(screen.getByRole("checkbox", { name: /我确认查询/ }));
    fireEvent.click(screen.getByRole("button", { name: "获取资料预览" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("先找回原预览");
    expect(screen.getByLabelText("公开查询内容")).toHaveValue("合成甲 600011 最新公告");
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });

  it("renders untrusted text literally, preserves expired/future rows, and blocks analysis", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(url.includes("/evidence?") ? json({ as_of: "2026-10-15T02:00:00Z", items: [{ ...evidence, freshness_status: "EXPIRED" }, { ...evidence, evidence_id: "future", title: "未来资料", freshness_status: "NOT_YET_AVAILABLE" }] }) : defaults(url))));
    const { container } = render(<ResearchPage />);
    expect(await screen.findByText("已过期 · 不用于新分析")).toBeVisible();
    expect(screen.getByText("尚未可用 · 不用于新分析")).toBeVisible();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
    expect(screen.getByRole("button", { name: "选择组合并分析" })).toBeDisabled();
  });

  it("discards old instrument evidence when the user switches targets", async () => {
    let release!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn((url: string) => url.includes("synthetic-a/evidence") ? new Promise<Response>((resolve) => { release = resolve; }) : Promise.resolve(defaults(url))));
    render(<ResearchPage />);
    await screen.findByDisplayValue("合成甲 600011 最新公告");
    fireEvent.click(screen.getByRole("button", { name: "选择乙" }));
    await waitFor(() => expect(screen.getByLabelText("公开查询内容")).toHaveValue("合成乙 600012 最新公告"));
    await act(async () => release(json({ as_of: "2026-10-15T02:00:00Z", items: [evidence] })));
    expect(screen.queryByText("合成公告")).not.toBeInTheDocument();
    expect(screen.getByText("这个标的还没有已存资料")).toBeVisible();
  });

  it("requires a second confirmation and a portfolio before model analysis", async () => {
    const fetcher = vi.fn((url: string) => Promise.resolve(url.includes("/evidence?") ? json({ as_of: "2026-10-15T02:00:00Z", items: [evidence] }) : defaults(url)));
    vi.stubGlobal("fetch", fetcher);
    render(<ResearchPage />);
    await screen.findByText("合成公告");
    expect(screen.getByRole("button", { name: "选择组合并分析" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "用于本次分析 合成公告" }));
    fireEvent.click(screen.getByRole("button", { name: "选择组合并分析" }));
    expect(await screen.findByRole("option", { name: "合成组合 · CNY" })).toBeVisible();
    expect(screen.getByRole("button", { name: "确认启动分析" })).toBeDisabled();
    expect(fetcher.mock.calls.some(([url]) => url.includes("analysis-runs"))).toBe(false);
  });

  it("restores confirmed preview from its URL without paying again", async () => {
    window.history.replaceState(null, "", "/research?instrument_id=synthetic-a&preview_id=synthetic-preview");
    const fetcher = vi.fn((url: string) => Promise.resolve(url.includes("/previews/") ? json({ ...draft, confirmation: [{ candidate_id: "candidate-one", evidence_id: evidence.evidence_id, reused: false }] }) : url.includes("/evidence?") ? json({ as_of: draft.as_of, items: [evidence] }) : defaults(url)));
    vi.stubGlobal("fetch", fetcher);
    render(<ResearchPage />);
    expect(await screen.findByRole("checkbox", { name: "用于本次分析 合成公告" })).toBeChecked();
    expect(screen.getByLabelText("公开查询内容")).toHaveValue("合成公开查询");
    expect(fetcher.mock.calls.every(([url]) => !url.includes("/providers/"))).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "清空分析选择" }));
    expect(screen.getByRole("button", { name: "选择组合并分析" })).toBeDisabled();
  });

  it("does not open model confirmation when saving a preview fails", async () => {
    window.history.replaceState(null, "", "/research?instrument_id=synthetic-a&preview_id=synthetic-preview");
    const fetcher = vi.fn((url: string, init?: RequestInit) => Promise.resolve(init?.method === "POST" ? new Response(JSON.stringify({ detail: "research_preview_expired" }), { status: 410 }) : url.includes("/previews/") ? json(draft) : defaults(url)));
    vi.stubGlobal("fetch", fetcher);
    render(<ResearchPage />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "保存候选 合成公告" }));
    fireEvent.click(screen.getByRole("button", { name: "保存所选并继续分析" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("预览确认窗口已过期");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    expect(fetcher.mock.calls.some(([url]) => url.includes("analysis-runs"))).toBe(false);
  });
});
