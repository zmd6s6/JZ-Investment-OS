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
  for (const failedRefresh of [false, true]) {
    test(`independent ${kind} UNKNOWN must not replay ${failedRefresh ? "after failed explicit refresh" : "before any explicit refresh"}`, async () => {
      const fetch = mock(), original = fetch.getMockImplementation()!;
      await open();
      if (kind === "save") { fill(); await prepare(); }
      else fireEvent.click(screen.getByLabelText(/我已核对此保存月度授权/));
      const isWrite = (url: unknown, init?: RequestInit) => init?.method === "POST" && (kind === "save" ? String(url) === "/api/v1/runtime/monthly" : String(url).endsWith("/mode"));
      fetch.mockImplementation(async (url, init) => isWrite(url, init) ? new Promise(() => {}) : original(url, init));
      vi.useFakeTimers();
      if (kind === "save") save(); else fireEvent.click(screen.getByRole("button", { name: "暂停月度复核" }));
      await advance();
      expect(screen.getByRole("region", { name: kind === "save" ? "月度保存结果待核对" : "月度启停结果待核对" })).toBeVisible();
      if (failedRefresh) {
        fetch.mockImplementation(async (url, init) => String(url) === "/api/v1/runtime/monthly" && !init?.method ? response({detail:"synthetic GET unavailable"}, 503) : original(url, init));
        fireEvent.click(screen.getByRole("button", { name: "刷新月度状态与报告" }));
        await advance(0);
        expect(screen.getByRole("alert")).toHaveTextContent("只读状态加载失败");
      }
      fetch.mockImplementation(original);
      fireEvent.click(screen.getByRole("button", { name: kind === "save" ? "已核对，使用原请求恢复月度保存" : "已核对，使用原请求恢复月度启停" }));
      await advance(0);
      const writes = fetch.mock.calls.filter(([url, init]) => isWrite(url, init));
      // The published recovery procedure requires the read-only reconciliation first.
      expect(writes).toHaveLength(1);
    });
  }
}

for (const kind of ["save", "mode"] as const) {
  test(`${kind} a successful explicit refresh before UNKNOWN does not authorize later recovery`, async () => {
    const fetch = mock(), original = fetch.getMockImplementation()!; await open();
    vi.useFakeTimers(); fireEvent.click(screen.getByRole("button", { name: "刷新月度状态与报告" })); await advance(0);
    if (kind === "save") { fill(); fireEvent.click(screen.getByRole("button", { name: "预览完整月度授权（不保存）" })); await advance(0); }
    else fireEvent.click(screen.getByLabelText(/我已核对此保存月度授权/));
    const isWrite = (url: unknown, init?: RequestInit) => init?.method === "POST" && (kind === "save" ? String(url) === "/api/v1/runtime/monthly" : String(url).endsWith("/mode"));
    fetch.mockImplementation(async (url, init) => isWrite(url, init) ? new Promise(() => {}) : original(url, init));
    if (kind === "save") save(); else fireEvent.click(screen.getByRole("button", { name: "暂停月度复核" })); await advance();
    const label = kind === "save" ? "已核对，使用原请求恢复月度保存" : "已核对，使用原请求恢复月度启停";
    expect(screen.getByRole("button", { name: label })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: label })); await advance(0);
    expect(fetch.mock.calls.filter(([url, init]) => isWrite(url, init))).toHaveLength(1);
  });

  test(`${kind} successful unrelated frozen-report GET cannot reconcile an UNKNOWN write`, async () => {
    const fetch = mock(), original = fetch.getMockImplementation()!;
    const report = { report_id: "frozen", schedule_id: "other-schedule", period_start: "2026-11-01", period_end: "2026-11-30", phase: "CLOSED_WEEK_SKIPPED", knowledge_as_of: "2026-11-09T00:00:00Z", recorded_at: "2026-11-09T00:00:00Z", usable_until: "2026-12-01T00:00:00Z", usable: true, holdings: [], unknowns: [], recovery: [], local_inputs: null };
    const base = async (url: unknown, init?: RequestInit) => String(url).endsWith("/history") ? response([report]) : String(url).endsWith("/replay") ? response(report) : original(url as RequestInfo, init);
    fetch.mockImplementation(base); await open();
    if (kind === "save") { fill(); await prepare(); } else fireEvent.click(screen.getByLabelText(/我已核对此保存月度授权/));
    const isWrite = (url: unknown, init?: RequestInit) => init?.method === "POST" && (kind === "save" ? String(url) === "/api/v1/runtime/monthly" : String(url).endsWith("/mode"));
    fetch.mockImplementation(async (url, init) => isWrite(url, init) ? new Promise(() => {}) : base(url, init));
    vi.useFakeTimers(); if (kind === "save") save(); else fireEvent.click(screen.getByRole("button", { name: "暂停月度复核" })); await advance();
    fireEvent.click(screen.getByRole("button", { name: "打开月报冻结快照" })); await advance(0);
    expect(screen.getByRole("region", { name: "月报冻结快照" })).toBeVisible();
    const label = kind === "save" ? "已核对，使用原请求恢复月度保存" : "已核对，使用原请求恢复月度启停";
    expect(screen.getByRole("button", { name: label })).toBeDisabled();
    expect(fetch.mock.calls.filter(([url, init]) => isWrite(url, init))).toHaveLength(1);
  });

  test(`${kind} recovery requires successful refresh for each UNKNOWN occurrence and ignores an older timed-out refresh`, async () => {
    const fetch = mock(), original = fetch.getMockImplementation()!; await open();
    if (kind === "save") { fill(); await prepare(); } else fireEvent.click(screen.getByLabelText(/我已核对此保存月度授权/));
    const isWrite = (url: unknown, init?: RequestInit) => init?.method === "POST" && (kind === "save" ? String(url) === "/api/v1/runtime/monthly" : String(url).endsWith("/mode"));
    const writes = () => fetch.mock.calls.filter(([url, init]) => isWrite(url, init));
    let failWrite = true, hangRead = false;
    const oldRead = pending<Response>();
    fetch.mockImplementation(async (url, init) => {
      if (isWrite(url, init)) return failWrite ? new Promise(() => {}) : response(config);
      if (hangRead && String(url) === "/api/v1/runtime/monthly") return oldRead.promise;
      return original(url, init);
    });
    const label = kind === "save" ? "已核对，使用原请求恢复月度保存" : "已核对，使用原请求恢复月度启停";
    vi.useFakeTimers();
    if (kind === "save") save(); else fireEvent.click(screen.getByRole("button", { name: "暂停月度复核" }));
    await advance(); expect(writes()).toHaveLength(1); expect(screen.getByRole("button", { name: label })).toBeDisabled();
    // A read that later resolves successfully after its deadline cannot grant permission.
    hangRead = true; fireEvent.click(screen.getByRole("button", { name: "刷新月度状态与报告" })); await advance();
    expect(screen.getByRole("button", { name: label })).toBeDisabled();
    hangRead = false; fireEvent.click(screen.getByRole("button", { name: "刷新月度状态与报告" })); await advance(0);
    const recoveryButton = screen.getByRole("button", { name: label }); expect(recoveryButton).toBeEnabled();
    // Capture a queued handler from a permitted render: handler checks must
    // remain fail-closed even after that render's permission has been consumed.
    const reactProps = Object.keys(recoveryButton).find(key => key.startsWith("__reactProps$"))!;
    const queuedRecovery = (Reflect.get(recoveryButton, reactProps) as { onClick: () => void }).onClick;
    fireEvent.click(recoveryButton); await advance();
    expect(writes()).toHaveLength(2); expect(screen.getByRole("button", { name: label })).toBeDisabled();
    await act(async () => { oldRead.resolve(response([config])); queuedRecovery(); }); await advance(0);
    expect(writes()).toHaveLength(2); expect(screen.getByRole("button", { name: label })).toBeDisabled();
    failWrite = false;
    fireEvent.click(screen.getByRole("button", { name: "刷新月度状态与报告" })); await advance(0);
    expect(screen.getByRole("button", { name: label })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: label })); await advance(0);
    expect(writes()).toHaveLength(3);
    expect(writes().every(([, init]) => init?.body === writes()[0][1]?.body)).toBe(true);
  });

  test(`${kind} failed refresh revokes an earlier successful readback even for an already queued recovery handler`, async () => {
    const fetch = mock(), original = fetch.getMockImplementation()!; await open();
    if (kind === "save") { fill(); await prepare(); } else fireEvent.click(screen.getByLabelText(/我已核对此保存月度授权/));
    const isWrite = (url: unknown, init?: RequestInit) => init?.method === "POST" && (kind === "save" ? String(url) === "/api/v1/runtime/monthly" : String(url).endsWith("/mode"));
    fetch.mockImplementation(async (url, init) => isWrite(url, init) ? new Promise(() => {}) : original(url, init));
    vi.useFakeTimers(); if (kind === "save") save(); else fireEvent.click(screen.getByRole("button", { name: "暂停月度复核" })); await advance();
    fetch.mockImplementation(original);
    fireEvent.click(screen.getByRole("button", { name: "刷新月度状态与报告" })); await advance(0);
    const label = kind === "save" ? "已核对，使用原请求恢复月度保存" : "已核对，使用原请求恢复月度启停";
    const button = screen.getByRole("button", { name: label }); expect(button).toBeEnabled();
    const props = Object.keys(button).find(key => key.startsWith("__reactProps$"))!;
    const queuedRecovery = (Reflect.get(button, props) as { onClick: () => void }).onClick;
    fetch.mockImplementation(async (url, init) => String(url) === "/api/v1/runtime/monthly" && !init?.method ? response({ detail: "synthetic failed readback" }, 503) : original(url, init));
    fireEvent.click(screen.getByRole("button", { name: "刷新月度状态与报告" })); await advance(0);
    expect(screen.getByRole("button", { name: label })).toBeDisabled();
    await act(async () => { queuedRecovery(); }); await advance(0);
    expect(fetch.mock.calls.filter(([url, init]) => isWrite(url, init))).toHaveLength(1);
    // A replacement successful readback also has a new lease; the callback
    // whose earlier readback was revoked must not borrow that replacement.
    fetch.mockImplementation(original);
    fireEvent.click(screen.getByRole("button", { name: "刷新月度状态与报告" })); await advance(0);
    expect(screen.getByRole("button", { name: label })).toBeEnabled();
    await act(async () => { queuedRecovery(); }); await advance(0);
    expect(fetch.mock.calls.filter(([url, init]) => isWrite(url, init))).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: label })); await advance(0);
    const writes = fetch.mock.calls.filter(([url, init]) => isWrite(url, init));
    expect(writes).toHaveLength(2); expect(writes[1][1]?.body).toBe(writes[0][1]?.body);
  });
}


