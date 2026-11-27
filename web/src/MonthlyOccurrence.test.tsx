import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MonthlyReviewPanel } from "./MonthlyReviewPanel";

const DEADLINE = 15000;
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const position = { instrument_id: "22222222-2222-4222-8222-222222222222", name: "合成持仓", symbol: "600000" };
const book = { portfolio_id: "11111111-1111-4111-8111-111111111111", name: "合成组合", positions: [position] };
const calendar = { venue: "SSE", import_id: "33333333-3333-4333-8333-333333333333", source_name: "合成日历", source_version: "v1" };
const prepared = (command: unknown) => ({ command, content_hash: "a".repeat(64), calendar_source: "合成日历", calendar_version: "v1", calendar_hash: "b".repeat(64), members: [position] });
const command = { name: "原月任务", coverage_start: "2026-11-01", coverage_end: "2026-11-30", quote_source_name: "合成来源", evidence_source_names: [], valid_from: "2026-11-01T00:00:00Z", valid_until: "2026-12-01T00:00:00Z", retention_days: 7 };
const config = { schedule_id: "original", revision_id: "r1", version: 4, enabled: false, revoked: false, blocker: "MONTHLY_PAUSED", prepared: prepared(command) };
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });
function pending<T>() { let resolve!: (value: T) => void; return { promise: new Promise<T>(done => { resolve = done; }), resolve: (value: T) => resolve(value) }; }
function mock() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    const path = String(url);
    if (path === "/api/v1/portfolios") return response([book]);
    if (path === "/api/v1/calendar") return response({ configurations: [calendar] });
    if (path.endsWith("/preview")) return response(prepared(JSON.parse(String(init?.body))));
    if (path === "/api/v1/runtime/monthly") return response(init?.method === "POST" ? config : [config]);
    return response([]);
  });
}
async function open() { render(<MonthlyReviewPanel />); await screen.findByRole("option", { name: "合成组合" }); }
function fill() {
  for (const [label, value] of [["月度任务名称", "保留的月草稿"], ["月度组合", book.portfolio_id], ["月度显式日历", calendar.import_id], ["首月起日（必须1日）", "2026-11-01"], ["末月末日（必须月末）", "2026-11-30"], ["月度授权开始（浏览器本地时区）", "2026-11-01T00:00"], ["月度授权截止", "2026-12-01T00:00"], ["月报使用期限（天）", "7"], ["月度本地报价来源", "合成来源"]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(screen.getByLabelText(/我独立确认完整月覆盖/));
}
async function prepare() { fireEvent.click(screen.getByRole("button", { name: "预览完整月度授权（不保存）" })); await screen.findByRole("heading", { name: "完整月度授权预览" }); }
function save() { fireEvent.click(screen.getByLabelText(/已核对本次全部月度范围/)); fireEvent.click(screen.getByRole("button", { name: "保存月度授权为暂停" })); }
async function advance(ms = DEADLINE) { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); }

for (const kind of ["save", "mode"] as const) {
  test(`independent ${kind} consumed old handler cannot redeem a later UNKNOWN occurrence readback`, async () => {
    const fetch = mock(), original = fetch.getMockImplementation()!; await open();
    if (kind === "save") { fill(); await prepare(); } else fireEvent.click(screen.getByLabelText(/我已核对此保存月度授权/));
    const isWrite = (url: unknown, init?: RequestInit) => init?.method === "POST" && (kind === "save" ? String(url) === "/api/v1/runtime/monthly" : String(url).endsWith("/mode"));
    fetch.mockImplementation(async (url, init) => isWrite(url, init) ? new Promise(() => {}) : original(url, init));
    const label = kind === "save" ? "已核对，使用原请求恢复月度保存" : "已核对，使用原请求恢复月度启停";
    vi.useFakeTimers(); if (kind === "save") save(); else fireEvent.click(screen.getByRole("button", { name: "暂停月度复核" })); await advance();
    fireEvent.click(screen.getByRole("button", { name: "刷新月度状态与报告" })); await advance(0);
    const button = screen.getByRole("button", { name: label }); expect(button).toBeEnabled();
    const props = Object.keys(button).find(key => key.startsWith("__reactProps$"))!;
    const oldRecovery = (Reflect.get(button, props) as { onClick: () => void }).onClick;
    fireEvent.click(button); await advance();
    expect(screen.getByRole("button", { name: label })).toBeDisabled();
    expect(fetch.mock.calls.filter(([url, init]) => isWrite(url, init))).toHaveLength(2);
    // Explicitly reconcile the new UNKNOWN occurrence. Its current handler may act,
    // but a callback retained from the consumed earlier occurrence must not do so.
    fireEvent.click(screen.getByRole("button", { name: "刷新月度状态与报告" })); await advance(0);
    expect(screen.getByRole("button", { name: label })).toBeEnabled();
    await act(async () => { oldRecovery(); }); await advance(0);
    expect(fetch.mock.calls.filter(([url, init]) => isWrite(url, init))).toHaveLength(2);
    // The current occurrence's handler still recovers the same immutable
    // request. This is a controlled retained-callback model, not a claim of
    // a naturally reproduced browser interaction.
    fetch.mockImplementation(original);
    fireEvent.click(screen.getByRole("button", { name: label })); await advance(0);
    const writes = fetch.mock.calls.filter(([url, init]) => isWrite(url, init));
    expect(writes).toHaveLength(3);
    expect(writes.every(([, init]) => init?.body === writes[0][1]?.body)).toBe(true);
  });
}



for (const kind of ["save", "mode"] as const) {
  test(`monthly ${kind} consumed recovery handler cannot POST again after confirmed receipt cleared UNKNOWN`, async () => {
    const fetch = mock(), original = fetch.getMockImplementation()!; await open();
    if (kind === "save") { fill(); await prepare(); } else fireEvent.click(screen.getByLabelText(/我已核对此保存月度授权/));
    const isWrite = (url: unknown, init?: RequestInit) => init?.method === "POST" && (kind === "save" ? String(url) === "/api/v1/runtime/monthly" : String(url).endsWith("/mode"));
    fetch.mockImplementation(async (url, init) => isWrite(url, init) ? new Promise(() => {}) : original(url, init));
    vi.useFakeTimers(); if (kind === "save") save(); else fireEvent.click(screen.getByRole("button", { name: "暂停月度复核" })); await advance();
    fireEvent.click(screen.getByRole("button", { name: "刷新月度状态与报告" })); await advance(0);
    const label = kind === "save" ? "已核对，使用原请求恢复月度保存" : "已核对，使用原请求恢复月度启停";
    const button = screen.getByRole("button", { name: label });
    const props = Object.keys(button).find(key => key.startsWith("__reactProps$"))!;
    const oldRecovery = (Reflect.get(button, props) as { onClick: () => void }).onClick;
    fetch.mockImplementation(original); fireEvent.click(button); await advance(0);
    expect(screen.queryByRole("button", { name: label })).toBeNull();
    await act(async () => { oldRecovery(); }); await advance(0);
    expect(fetch.mock.calls.filter(([url, init]) => isWrite(url, init))).toHaveLength(2);
  });
}
