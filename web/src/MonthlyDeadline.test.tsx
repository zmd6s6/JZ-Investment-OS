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

for (const stage of ["fetch", "body"] as const) {
  test(`monthly hung ${stage} GET unlocks exactly at deadline and late success cannot replace an explicit reread`, async () => {
    const fetch = mock(), original = fetch.getMockImplementation()!;
    await open(); fill();
    const held = pending<unknown>();
    fetch.mockImplementation(async (url, init) => {
      if (String(url) !== "/api/v1/runtime/monthly") return original(url, init);
      if (stage === "fetch") return held.promise as Promise<Response>;
      const value = response([]); value.json = () => held.promise; return value;
    });
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "刷新月度状态与报告" }));
    await advance(DEADLINE - 1);
    expect(screen.getByRole("button", { name: "刷新月度状态与报告" })).toBeDisabled();
    await advance(1);
    expect(screen.getByRole("button", { name: "刷新月度状态与报告" })).toBeEnabled();
    expect(screen.getByRole("alert")).toHaveTextContent(/15秒/);
    expect(screen.getByLabelText("月度任务名称")).toHaveValue("保留的月草稿");
    expect(screen.getByRole("button", { name: "预览完整月度授权（不保存）" })).toBeDisabled();
    fetch.mockImplementation(original);
    fireEvent.click(screen.getByRole("button", { name: "刷新月度状态与报告" }));
    await advance(0);
    expect(screen.getByRole("heading", { name: /原月任务/ })).toBeVisible();
    await act(async () => { held.resolve(stage === "fetch" ? response([{ ...config, prepared: prepared({ ...command, name: "迟到错误任务" }) }]) : [{ ...config, prepared: prepared({ ...command, name: "迟到错误任务" }) }]); });
    expect(screen.queryByRole("heading", { name: /迟到错误任务/ })).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  });

  test(`monthly hung ${stage} save freezes exact request once and late response cannot erase unknown-result recovery`, async () => {
    const fetch = mock(), original = fetch.getMockImplementation()!;
    await open(); fill(); await prepare();
    const held = pending<unknown>();
    fetch.mockImplementation(async (url, init) => {
      if (String(url) !== "/api/v1/runtime/monthly" || init?.method !== "POST") return original(url, init);
      if (stage === "fetch") return held.promise as Promise<Response>;
      const value = response(config); value.json = () => held.promise; return value;
    });
    vi.useFakeTimers(); save(); await advance();
    expect(screen.getByRole("region", { name: "月度保存结果待核对" })).toBeVisible();
    expect(screen.getByRole("button", { name: "刷新月度状态与报告" })).toBeEnabled();
    expect(screen.getByLabelText("月度任务名称")).toHaveValue("保留的月草稿");
    expect(screen.getByLabelText("月度任务名称")).toBeDisabled();
    expect(screen.getByRole("button", { name: "修订此月度授权" })).toBeDisabled();
    const writes = () => fetch.mock.calls.filter(([url, init]) => String(url) === "/api/v1/runtime/monthly" && init?.method === "POST");
    expect(writes()).toHaveLength(1);
    await act(async () => { held.resolve(stage === "fetch" ? response(config) : config); });
    expect(screen.getByRole("region", { name: "月度保存结果待核对" })).toBeVisible();
    fetch.mockImplementation(original);
    fireEvent.click(screen.getByRole("button", { name: "刷新月度状态与报告" })); await advance(0);
    expect(writes()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "已核对，使用原请求恢复月度保存" })); await advance(0);
    expect(writes()).toHaveLength(2); expect(writes()[0][1]?.body).toBe(writes()[1][1]?.body);
    expect(screen.queryByRole("region", { name: "月度保存结果待核对" })).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("月度授权已保存, 默认暂停");
    expect(vi.getTimerCount()).toBe(0);
  });
}

test("monthly hung preview is a read-only timeout, preserves draft and discards a late preview", async () => {
  const fetch = mock(), original = fetch.getMockImplementation()!; await open(); fill();
  const held = pending<Response>(); fetch.mockImplementation(async (url, init) => String(url).endsWith("/preview") ? held.promise : original(url, init));
  vi.useFakeTimers(); fireEvent.click(screen.getByRole("button", { name: "预览完整月度授权（不保存）" })); await advance();
  expect(screen.getByRole("button", { name: "预览完整月度授权（不保存）" })).toBeEnabled();
  expect(screen.getByRole("alert")).toHaveTextContent("预览未保存");
  expect(screen.queryByRole("region", { name: "月度保存结果待核对" })).toBeNull();
  await act(async () => { held.resolve(response(prepared(command))); });
  expect(screen.queryByRole("heading", { name: "完整月度授权预览" })).toBeNull();
  expect(screen.getByLabelText("月度任务名称")).toHaveValue("保留的月草稿");
});

test("monthly unmount cancels pending whole-body read and clears timers even when transport ignores abort", async () => {
  const fetch = mock(), original = fetch.getMockImplementation()!; await open();
  let signal: AbortSignal | null | undefined;
  fetch.mockImplementation(async (url, init) => {
    if (String(url) !== "/api/v1/runtime/monthly") return original(url, init);
    signal = init?.signal; const value = response([]); value.json = () => new Promise(() => {}); return value;
  });
  vi.useFakeTimers(); fireEvent.click(screen.getByRole("button", { name: "刷新月度状态与报告" })); await advance(0);
  expect(signal).toBeInstanceOf(AbortSignal); cleanup(); await advance(0);
  expect(signal?.aborted).toBe(true); expect(vi.getTimerCount()).toBe(0);
});

for (const stage of ["fetch", "body"] as const) {
  test(`monthly hung ${stage} mode preserves original UUID action and CAS for explicit recovery after refresh`, async () => {
    const fetch = mock(), original = fetch.getMockImplementation()!; await open();
    const held = pending<unknown>();
    fetch.mockImplementation(async (url, init) => {
      if (!String(url).endsWith("/mode")) return original(url, init);
      if (stage === "fetch") return held.promise as Promise<Response>;
      const value = response(config); value.json = () => held.promise; return value;
    });
    fireEvent.click(screen.getByLabelText(/我已核对此保存月度授权/));
    vi.useFakeTimers(); fireEvent.click(screen.getByRole("button", { name: "暂停月度复核" })); await advance();
    expect(screen.getByRole("region", { name: "月度启停结果待核对" })).toHaveTextContent("PAUSE");
    expect(screen.getByRole("button", { name: "修订此月度授权" })).toBeDisabled();
    const writes = () => fetch.mock.calls.filter(([url]) => String(url).endsWith("/mode"));
    expect(writes()).toHaveLength(1);
    fetch.mockImplementation(async (url, init) => String(url) === "/api/v1/runtime/monthly" ? response([{ ...config, version: 9 }]) : original(url, init));
    fireEvent.click(screen.getByRole("button", { name: "刷新月度状态与报告" })); await advance(0);
    expect(screen.getByText(/版本9/)).toBeVisible();
    await act(async () => { held.resolve(stage === "fetch" ? response(config) : config); });
    expect(screen.getByRole("region", { name: "月度启停结果待核对" })).toBeVisible();
    expect(screen.getByRole("button", { name: "启用月度复核" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "已核对，使用原请求恢复月度启停" })); await advance(0);
    expect(writes()).toHaveLength(2); expect(writes()[0][1]?.body).toBe(writes()[1][1]?.body);
    expect(JSON.parse(String(writes()[1][1]?.body))).toMatchObject({ expected_version: 4, action: "PAUSE" });
    expect(screen.queryByRole("region", { name: "月度启停结果待核对" })).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("月度命令已确认");
  });
}

test("monthly timed-out current-CAS read cannot replace a subsequently selected task or its draft", async () => {
  const fetch = mock(), original = fetch.getMockImplementation()!; await open(); fill();
  const held = pending<Response>();
  fetch.mockImplementation(async (url, init) => String(url) === "/api/v1/runtime/monthly" ? held.promise : original(url, init));
  vi.useFakeTimers(); fireEvent.click(screen.getByRole("button", { name: "修订此月度授权" })); await advance();
  expect(screen.getByRole("alert")).toHaveTextContent("读取原授权失败，草稿保留");
  expect(screen.getByLabelText("月度任务名称")).toHaveValue("保留的月草稿");
  const next = { ...config, schedule_id: "task-b", version: 9, prepared: prepared({ ...command, name: "新选择B" }) };
  fetch.mockImplementation(async (url, init) => String(url) === "/api/v1/runtime/monthly" ? response([next]) : original(url, init));
  fireEvent.click(screen.getByRole("button", { name: "刷新月度状态与报告" })); await advance(0);
  fireEvent.click(screen.getByRole("button", { name: "修订此月度授权" })); await advance(0);
  expect(screen.getByLabelText("月度任务名称")).toHaveValue("新选择B");
  await act(async () => { held.resolve(response([config])); });
  expect(screen.getByLabelText("月度任务名称")).toHaveValue("新选择B");
  expect(screen.getByText(/正在修订原月度任务task-b · 当前核对版本9/)).toBeVisible();
});

test("monthly report body timeout clears prior detail and late body cannot replace a newer selected report", async () => {
  const fetch = mock(), original = fetch.getMockImplementation()!;
  const report = (id: string) => ({ report_id: id, schedule_id: "original", period_start: "2026-11-01", period_end: "2026-11-30", phase: "CLOSED_WEEK_SKIPPED", knowledge_as_of: "2026-11-09T00:00:00Z", recorded_at: "2026-11-09T00:00:00Z", content_hash: id, holdings: [], unknowns: [], recovery: [], local_inputs: null, usable: true, usable_until: "2026-12-01T00:00:00Z" });
  fetch.mockImplementation(async (url, init) => String(url).endsWith("/history") ? response([report("a"), report("b")]) : String(url).endsWith("/replay") ? response(report("a")) : original(url, init));
  await open(); fireEvent.click(screen.getAllByRole("button", { name: "打开月报冻结快照" })[0]);
  await screen.findByRole("region", { name: "月报冻结快照" });
  const held = pending<unknown>();
  fetch.mockImplementation(async (url, init) => {
    if (String(url).includes("/reports/a/replay")) { const value = response(report("a")); value.json = () => held.promise; return value; }
    return String(url).endsWith("/replay") ? response(report("b")) : original(url, init);
  });
  vi.useFakeTimers(); fireEvent.click(screen.getAllByRole("button", { name: "打开月报冻结快照" })[0]); await advance();
  expect(screen.queryByRole("region", { name: "月报冻结快照" })).toBeNull();
  expect(screen.getByRole("alert")).toHaveTextContent("已清空旧正文");
  fireEvent.click(screen.getAllByRole("button", { name: "打开月报冻结快照" })[1]); await advance(0);
  expect(screen.getByRole("region", { name: "月报冻结快照" })).toBeVisible();
  await act(async () => { held.resolve({ ...report("a"), phase: "迟到A" }); });
  expect(screen.queryByRole("heading", { name: /迟到A/ })).toBeNull();
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true);
});

test("monthly timeout preserves dispatched save identity even if a queued draft change arrives while locked", async () => {
  const fetch = mock(), original = fetch.getMockImplementation()!; await open(); fill(); await prepare();
  fetch.mockImplementation(async (url, init) => String(url) === "/api/v1/runtime/monthly" && init?.method === "POST" ? new Promise(() => {}) : original(url, init));
  vi.useFakeTimers(); save();
  const sent = fetch.mock.calls.find(([url, init]) => String(url) === "/api/v1/runtime/monthly" && init?.method === "POST")!;
  fireEvent.change(screen.getByLabelText("月度任务名称"), { target: { value: "排队到达的草稿" } });
  await advance();
  expect(screen.getByRole("region", { name: "月度保存结果待核对" })).toHaveTextContent(JSON.parse(String(sent[1]?.body)).command.request_id);
  expect(screen.getByLabelText("月度任务名称")).toHaveValue("排队到达的草稿");
  fetch.mockImplementation(original);
  fireEvent.click(screen.getByRole("button", { name: "刷新月度状态与报告" })); await advance(0);
  fireEvent.click(screen.getByRole("button", { name: "已核对，使用原请求恢复月度保存" })); await advance(0);
  const writes = fetch.mock.calls.filter(([url, init]) => String(url) === "/api/v1/runtime/monthly" && init?.method === "POST");
  expect(writes).toHaveLength(2); expect(writes[1][1]?.body).toBe(sent[1]?.body);
});

test("monthly expired initial read cannot overwrite a newer explicit successful refresh with stale failure", async () => {
  const fetch = mock(), original = fetch.getMockImplementation()!;
  fetch.mockImplementation(async (url, init) => String(url) === "/api/v1/runtime/monthly" ? new Promise(() => {}) : original(url, init));
  vi.useFakeTimers(); render(<MonthlyReviewPanel />); await advance(0);
  fetch.mockImplementation(original);
  fireEvent.click(screen.getByRole("button", { name: "刷新月度状态与报告" })); await advance(0);
  expect(screen.getByRole("heading", { name: /原月任务/ })).toBeVisible();
  await advance();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByRole("heading", { name: /原月任务/ })).toBeVisible();
  expect(screen.getByRole("button", { name: "预览完整月度授权（不保存）" })).toBeEnabled();
});

for (const kind of ["save", "mode"] as const) {
  test(`monthly confirmed ${kind} receipt remains confirmed when only its subsequent refresh times out`, async () => {
    const fetch = mock(), original = fetch.getMockImplementation()!; await open();
    if (kind === "save") { fill(); await prepare(); }
    else fireEvent.click(screen.getByLabelText(/我已核对此保存月度授权/));
    let committed = false;
    fetch.mockImplementation(async (url, init) => {
      if (init?.method === "POST") { committed = true; return response(config); }
      if (committed && String(url) === "/api/v1/runtime/monthly") return new Promise(() => {});
      return original(url, init);
    });
    vi.useFakeTimers();
    if (kind === "save") save(); else fireEvent.click(screen.getByRole("button", { name: "暂停月度复核" }));
    await advance();
    expect(screen.getByRole("status")).toHaveTextContent("回执已确认");
    expect(screen.getByRole("alert")).toHaveTextContent("15秒");
    expect(screen.queryByRole("region", { name: "月度保存结果待核对" })).toBeNull();
    expect(screen.queryByRole("region", { name: "月度启停结果待核对" })).toBeNull();
    expect(screen.getByRole("button", { name: "刷新月度状态与报告" })).toBeEnabled();
    expect(fetch.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(kind === "save" ? 2 : 1);
  });
}

for (const kind of ["save", "mode"] as const) {
  test(`monthly ${kind} hung error-body decode reaches UNKNOWN and preserves exact dispatched body`, async () => {
    const fetch = mock(), original = fetch.getMockImplementation()!; await open();
    if (kind === "save") { fill(); await prepare(); } else fireEvent.click(screen.getByLabelText(/我已核对此保存月度授权/));
    const isWrite = (url: unknown, init?: RequestInit) => init?.method === "POST" && (kind === "save" ? String(url) === "/api/v1/runtime/monthly" : String(url).endsWith("/mode"));
    const held = pending<unknown>();
    fetch.mockImplementation(async (url, init) => {
      if (!isWrite(url, init)) return original(url, init);
      const value = response({ detail: "synthetic refusal body not delivered" }, 409); value.json = () => held.promise; return value;
    });
    vi.useFakeTimers(); if (kind === "save") save(); else fireEvent.click(screen.getByRole("button", { name: "暂停月度复核" }));
    await advance();
    const region = kind === "save" ? "月度保存结果待核对" : "月度启停结果待核对";
    expect(screen.getByRole("region", { name: region })).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("取消请求不等于回滚");
    expect(screen.getByRole("button", { name: "刷新月度状态与报告" })).toBeEnabled();
    await act(async () => { held.resolve({ detail: "late known refusal" }); });
    expect(screen.getByRole("region", { name: region })).toBeVisible();
    fetch.mockImplementation(original); fireEvent.click(screen.getByRole("button", { name: "刷新月度状态与报告" })); await advance(0);
    fireEvent.click(screen.getByRole("button", { name: kind === "save" ? "已核对，使用原请求恢复月度保存" : "已核对，使用原请求恢复月度启停" })); await advance(0);
    const writes = fetch.mock.calls.filter(([url, init]) => isWrite(url, init));
    expect(writes).toHaveLength(2); expect(writes[0][1]?.body).toBe(writes[1][1]?.body);
    expect(vi.getTimerCount()).toBe(0);
  });

  for (const elapsed of [DEADLINE - 1, DEADLINE, DEADLINE + 1]) {
    test(`monthly ${kind} body completed at monotonic elapsed ${elapsed} honors full-chain deadline even before timer`, async () => {
      const fetch = mock(), original = fetch.getMockImplementation()!; await open();
      if (kind === "save") { fill(); await prepare(); } else fireEvent.click(screen.getByLabelText(/我已核对此保存月度授权/));
      const isWrite = (url: unknown, init?: RequestInit) => init?.method === "POST" && (kind === "save" ? String(url) === "/api/v1/runtime/monthly" : String(url).endsWith("/mode"));
      const body = pending<unknown>();
      fetch.mockImplementation(async (url, init) => {
        if (!isWrite(url, init)) return original(url, init);
        const value = response(config); value.json = () => body.promise; return value;
      });
      vi.useFakeTimers(); const clock = vi.spyOn(performance, "now").mockReturnValue(100);
      if (kind === "save") save(); else fireEvent.click(screen.getByRole("button", { name: "暂停月度复核" }));
      await advance(0);
      await act(async () => { clock.mockReturnValue(100 + elapsed); body.resolve(config); });
      if (elapsed < DEADLINE) {
        expect(screen.queryByRole("region", { name: kind === "save" ? "月度保存结果待核对" : "月度启停结果待核对" })).toBeNull();
        expect(screen.getByRole("status")).toHaveTextContent(kind === "save" ? "月度授权已保存" : "月度命令已确认");
      } else {
        expect(screen.getByRole("region", { name: kind === "save" ? "月度保存结果待核对" : "月度启停结果待核对" })).toBeVisible();
        expect(screen.getByRole("alert")).toHaveTextContent("15秒");
      }
      expect(vi.getTimerCount()).toBe(0);
    });
  }
}
