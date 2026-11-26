import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { WeeklyReviewPanel } from "./WeeklyReviewPanel";

const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const position = { instrument_id: "22222222-2222-4222-8222-222222222222", symbol: "600000", name: "合成持仓" };
const watch = { instrument_id: "44444444-4444-4444-8444-444444444444", symbol: "600001", name: "当前观察项" };
const book = { portfolio_id: "11111111-1111-4111-8111-111111111111", name: "当前合成组合", positions: [position] };
const calendar = { venue: "SSE", import_id: "33333333-3333-4333-8333-333333333333", source_name: "当前合成日历", source_version: "v2" };
const manifest = Array.from({ length: 7 }, (_, i) => `2026-11-${String(i + 2).padStart(2, "0")},${i === 0 ? "OPEN" : "CLOSED"}`).join("\n");
const command = { name: "原周任务", portfolio_id: book.portfolio_id, watchlist_instrument_ids: [watch.instrument_id], calendar_import_id: "old-calendar", calendar_days: { "2026-11-02": "OPEN" }, coverage_start: "2026-11-02", coverage_end: "2026-11-08", quote_source_name: "明确本地来源", evidence_source_names: ["明确资料"], retention_days: 7, valid_from: "2026-11-01T00:00:00Z", valid_until: "2026-12-01T00:00:00Z" };
const prepared = (c = command) => ({ command: c, content_hash: "a".repeat(64), calendar_source: calendar.source_name, calendar_version: "v2", calendar_hash: "b".repeat(64), members: [position, watch] });
const config = (schedule_id = "original", version = 4) => ({ schedule_id, version, enabled: true, revoked: false, blocker: "WEEKLY_SCOPE_OR_CALENDAR_CHANGED", prepared: prepared() });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function mock() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    const path = String(url);
    if (path === "/api/v1/portfolios") return response([book]);
    if (path === "/api/v1/calendar") return response({ configurations: [calendar] });
    if (path === "/api/v1/watchlist") return response([watch]);
    if (path.endsWith("/preview")) return response(prepared(JSON.parse(String(init?.body))));
    if (path === "/api/v1/runtime/weekly") return response(init?.method === "POST" ? { ...config(), enabled: false } : [config()]);
    return response([]);
  });
}
async function revise() {
  fireEvent.click(await screen.findByRole("button", { name: "修订此周度授权" }));
  await screen.findByText(/已读取原周度任务当前版本/);
}
function chooseScope() {
  fireEvent.change(screen.getByLabelText("周度组合"), { target: { value: book.portfolio_id } });
  fireEvent.change(screen.getByLabelText("周度显式日历"), { target: { value: calendar.import_id } });
  fireEvent.change(screen.getByLabelText("逐日完整覆盖清单"), { target: { value: manifest } });
  fireEvent.click(screen.getByLabelText(/当前观察项/));
  fireEvent.click(screen.getByLabelText(/我独立确认完整周覆盖/));
}
async function preview() {
  fireEvent.click(screen.getByRole("button", { name: "预览完整周度授权（不保存）" }));
  await screen.findByRole("heading", { name: "完整周度授权预览" });
}
function save() {
  fireEvent.click(screen.getByLabelText(/已核对本次全部周度范围/));
  fireEvent.click(screen.getByRole("button", { name: "保存周度授权为暂停" }));
}

test("same weekly task revision rereads current CAS and requires explicit current watchlist calendar and per-date scope", async () => {
  const fetch = mock(), original = fetch.getMockImplementation()!;
  let reads = 0;
  fetch.mockImplementation(async (url, init) => String(url) === "/api/v1/runtime/weekly" && !init?.method ? response([config("original", ++reads === 1 ? 4 : 9)]) : original(url, init));
  render(<WeeklyReviewPanel />);
  await revise();
  expect(screen.getByLabelText("周度组合")).toHaveValue("");
  expect(screen.getByLabelText("周度显式日历")).toHaveValue("");
  expect(screen.getByLabelText("逐日完整覆盖清单")).toHaveValue("");
  expect(screen.getByLabelText(/当前观察项/)).not.toBeChecked();
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true);
  chooseScope(); await preview(); save();
  await screen.findByText(/周度授权已保存, 默认暂停/);
  const writes = fetch.mock.calls.filter(([, init]) => init?.method === "POST");
  expect(writes).toHaveLength(2);
  const value = JSON.parse(String(writes[1][1]?.body));
  expect(value.command).toMatchObject({ schedule_id: "original", expected_version: 9, calendar_import_id: calendar.import_id, watchlist_instrument_ids: [watch.instrument_id] });
  expect(Object.keys(value.command.calendar_days)).toHaveLength(7);
  expect(writes.some(([url]) => String(url).endsWith("/mode"))).toBe(false);
});

test("weekly CAS rejection keeps exact draft and same schedule, requires fresh current version and preview", async () => {
  const fetch = mock(), original = fetch.getMockImplementation()!;
  let version = 4;
  fetch.mockImplementation(async (url, init) => String(url) === "/api/v1/runtime/weekly" ? init?.method === "POST" ? response({ detail: { code: "WEEKLY_VERSION_CONFLICT", message: "版本冲突" } }, 422) : response([config("original", version)]) : original(url, init));
  render(<WeeklyReviewPanel />); await revise(); chooseScope(); await preview(); save();
  expect(await screen.findByRole("alert")).toHaveTextContent("草稿已保留");
  expect(screen.getByLabelText("逐日完整覆盖清单")).toHaveValue(manifest);
  expect(screen.getByLabelText("周度组合")).toHaveValue(book.portfolio_id);
  expect(screen.queryByRole("heading", { name: "完整周度授权预览" })).toBeNull();
  version = 7;
  fireEvent.click(screen.getByRole("button", { name: "核对当前版本（保留草稿）" }));
  await screen.findByText(/当前核对版本7/);
  expect(screen.getByLabelText(/我独立确认完整周覆盖/)).not.toBeChecked();
  fireEvent.click(screen.getByLabelText(/我独立确认完整周覆盖/)); await preview();
  const calls = fetch.mock.calls.filter(([url]) => String(url).endsWith("/preview"));
  expect(JSON.parse(String(calls.at(-1)?.[1]?.body))).toMatchObject({ schedule_id: "original", expected_version: 7 });
});

test("weekly unknown commit freezes original UUID and content through readonly refresh until explicit receipt recovery", async () => {
  const fetch = mock(), original = fetch.getMockImplementation()!;
  let writes = 0;
  fetch.mockImplementation(async (url, init) => {
    if (String(url) === "/api/v1/runtime/weekly" && init?.method === "POST" && ++writes === 1) throw new Error("synthetic lost committed response");
    return original(url, init);
  });
  render(<WeeklyReviewPanel />); await revise(); chooseScope(); await preview(); save();
  await screen.findByRole("region", { name: "周度保存结果待核对" });
  expect(screen.getByLabelText("周度任务名称")).toBeDisabled();
  expect(screen.getByRole("button", { name: "修订此周度授权" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "退出周度修订" })).toBeDisabled();
  fireEvent.click(screen.getByLabelText(/我已核对此保存周度授权/));
  expect(screen.getByRole("button", { name: "启用周度复核" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "刷新周度状态与报告" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "已核对，使用原请求恢复周度保存" })).toBeEnabled());
  expect(writes).toBe(1);
  fireEvent.click(screen.getByRole("button", { name: "已核对，使用原请求恢复周度保存" }));
  await screen.findByText(/周度授权已保存, 默认暂停/);
  const saved = fetch.mock.calls.filter(([url, init]) => String(url) === "/api/v1/runtime/weekly" && init?.method === "POST");
  expect(saved).toHaveLength(2); expect(saved[0][1]?.body).toBe(saved[1][1]?.body);
});

test("weekly current revision outside first 50 configurations is reached by readonly paged current-CAS lookup", async () => {
  const fetch = mock(), original = fetch.getMockImplementation()!;
  fetch.mockImplementation(async (url, init) => {
    if (String(url) === "/api/v1/runtime/weekly") return response(Array.from({ length: 50 }, (_, i) => config(`other${i}`)));
    if (String(url) === "/api/v1/runtime/weekly?offset=50") return response([config("original", 12)]);
    return original(url, init);
  });
  render(<WeeklyReviewPanel />);
  fireEvent.click(await screen.findByRole("button", { name: "加载更多周度授权" }));
  await waitFor(() => expect(screen.getAllByRole("button", { name: "修订此周度授权" })).toHaveLength(51));
  fireEvent.click(screen.getAllByRole("button", { name: "修订此周度授权" })[50]);
  await screen.findByText(/正在修订原周度任务original · 当前核对版本12/);
  expect(fetch.mock.calls.filter(([url]) => String(url).includes("?offset=50"))).toHaveLength(2);
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true);
});

test("weekly revoked and legacy authorization cannot be revised or resurrected after concurrent revoke", async () => {
  const fetch = mock(), original = fetch.getMockImplementation()!;
  let reads = 0;
  fetch.mockImplementation(async (url, init) => String(url) === "/api/v1/runtime/weekly" ? response([{ ...config(), revoked: ++reads > 1 }, { ...config("legacy"), prepared: null }]) : original(url, init));
  render(<WeeklyReviewPanel />);
  await screen.findByRole("button", { name: "刷新周度状态与报告" });
  await waitFor(() => expect(screen.getAllByRole("button", { name: "修订此周度授权" })).toHaveLength(2));
  expect(screen.getAllByRole("button", { name: "修订此周度授权" })[1]).toBeDisabled();
  fireEvent.click(screen.getAllByRole("button", { name: "修订此周度授权" })[0]);
  expect(await screen.findByRole("alert")).toHaveTextContent("永久撤销");
  expect(screen.queryByText(/正在修订原周度任务/)).toBeNull();
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true);
});

test("weekly switching tasks clears preview and consent, delayed version read locks other task and draft controls", async () => {
  const fetch = mock(), original = fetch.getMockImplementation()!;
  let resolve: ((value: Response) => void) | undefined, hold = false;
  fetch.mockImplementation(async (url, init) => String(url) === "/api/v1/runtime/weekly" && !init?.method ? hold ? new Promise<Response>(done => { resolve = done; }) : response([config(), { ...config("task-b"), prepared: prepared({ ...command, name: "任务B" }) }]) : original(url, init));
  render(<WeeklyReviewPanel />);
  await waitFor(() => expect(screen.getAllByRole("button", { name: "修订此周度授权" })).toHaveLength(2));
  fireEvent.click(screen.getAllByRole("button", { name: "修订此周度授权" })[0]);
  await screen.findByText(/正在修订原周度任务original/); chooseScope(); await preview();
  hold = true;
  fireEvent.click(screen.getAllByRole("button", { name: "修订此周度授权" })[1]);
  expect(screen.queryByRole("heading", { name: "完整周度授权预览" })).toBeNull();
  expect(screen.getByLabelText("周度任务名称")).toBeDisabled();
  expect(screen.getAllByRole("button", { name: "修订此周度授权" })[0]).toBeDisabled();
  resolve!(response([config(), { ...config("task-b", 8), prepared: prepared({ ...command, name: "任务B" }) }]));
  await screen.findByText(/正在修订原周度任务task-b · 当前核对版本8/);
  expect(screen.getByLabelText("周度任务名称")).toHaveValue("任务B");
  expect(screen.getByLabelText("逐日完整覆盖清单")).toHaveValue("");
  expect(screen.getByLabelText(/我独立确认完整周覆盖/)).not.toBeChecked();
});

test("weekly stale preview delivery after draft mutation is discarded and readonly refresh invalidates old preview", async () => {
  const fetch = mock(), original = fetch.getMockImplementation()!;
  let resolve: ((value: Response) => void) | undefined, body: typeof command;
  fetch.mockImplementation(async (url, init) => String(url).endsWith("/preview") ? new Promise<Response>(done => { resolve = done; body = JSON.parse(String(init?.body)); }) : original(url, init));
  render(<WeeklyReviewPanel />); await revise(); chooseScope();
  fireEvent.click(screen.getByRole("button", { name: "预览完整周度授权（不保存）" }));
  expect(screen.getByRole("button", { name: "退出周度修订" })).toBeDisabled();
  // Simulate an already queued change event while the server's preview is in flight.
  fireEvent.change(screen.getByLabelText("周度任务名称"), { target: { value: "新草稿" } });
  resolve!(response(prepared(body!)));
  await waitFor(() => expect(screen.getByRole("button", { name: "预览完整周度授权（不保存）" })).toBeEnabled());
  expect(screen.queryByRole("heading", { name: "完整周度授权预览" })).toBeNull();
  expect(screen.getByLabelText("周度任务名称")).toHaveValue("新草稿");
});

test("weekly completed preview is invalidated by readonly refresh and returning to new-task creation", async () => {
  const fetch = mock(); render(<WeeklyReviewPanel />); await revise(); chooseScope(); await preview();
  fireEvent.click(screen.getByRole("button", { name: "刷新周度状态与报告" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "刷新周度状态与报告" })).toBeEnabled());
  expect(screen.queryByRole("heading", { name: "完整周度授权预览" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "退出周度修订" }));
  expect(screen.getByRole("group", { name: "建立新的独立周度授权" })).toBeVisible();
  expect(screen.getByLabelText("逐日完整覆盖清单")).toHaveValue("");
  expect(fetch.mock.calls.some(([url, init]) => String(url) === "/api/v1/runtime/weekly" && init?.method === "POST")).toBe(false);
});

test("weekly watchlist change invalidates preview and independently confirmed scope", async () => {
  mock(); render(<WeeklyReviewPanel />); await revise(); chooseScope(); await preview();
  fireEvent.click(screen.getByLabelText(/当前观察项/));
  expect(screen.queryByRole("heading", { name: "完整周度授权预览" })).toBeNull();
  expect(screen.getByLabelText(/我独立确认完整周覆盖/)).not.toBeChecked();
});

test("weekly pending save prevents task switch and all new writes until original receipt completes", async () => {
  const fetch = mock(), original = fetch.getMockImplementation()!;
  let resolve: ((value: Response) => void) | undefined;
  fetch.mockImplementation(async (url, init) => String(url) === "/api/v1/runtime/weekly" && init?.method === "POST" ? new Promise<Response>(done => { resolve = done; }) : original(url, init));
  render(<WeeklyReviewPanel />); await revise(); chooseScope(); await preview(); save();
  expect(screen.getByRole("button", { name: "修订此周度授权" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "核对当前版本（保留草稿）" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "退出周度修订" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "刷新周度状态与报告" })).toBeDisabled();
  expect(screen.getByLabelText("周度任务名称")).toBeDisabled();
  resolve!(response({ ...config(), enabled: false }));
  await screen.findByText(/周度授权已保存, 默认暂停/);
  expect(screen.queryByText(/正在修订原周度任务/)).toBeNull();
  expect(fetch.mock.calls.filter(([url, init]) => String(url) === "/api/v1/runtime/weekly" && init?.method === "POST")).toHaveLength(1);
});
