import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MonthlyReviewPanel } from "./MonthlyReviewPanel";
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const book = { portfolio_id: "11111111-1111-4111-8111-111111111111", name: "合成月度组合", positions: [{ instrument_id: "22222222-2222-4222-8222-222222222222", symbol: "600000", name: "合成持仓" }] };
const calendar = { venue: "SSE", import_id: "33333333-3333-4333-8333-333333333333", source_name: "合成月度日历", source_version: "v1" };
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function mock() {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
        const path = String(url);
        if (path === "/api/v1/portfolios")
            return response([book]);
        if (path === "/api/v1/calendar")
            return response({ configurations: [calendar] });
        if (path.endsWith("/preview"))
            return response({ command: JSON.parse(String(init?.body)), content_hash: "a".repeat(64), calendar_source: calendar.source_name, calendar_version: "v1", calendar_hash: "b".repeat(64), members: book.positions });
        if (init?.method === "POST")
            return response({ enabled: false });
        return response([]);
    });
}
async function fill() {
    await screen.findByRole("option", { name: "合成月度组合" });
    for (const [label, value] of [["月度任务名称", "合成月报"], ["月度组合", book.portfolio_id], ["月度显式日历", calendar.import_id], ["首月起日（必须1日）", "2026-10-01"], ["末月末日（必须月末）", "2026-10-31"], ["月度授权开始（浏览器本地时区）", "2026-10-01T08:00"], ["月度授权截止", "2026-12-01T08:00"], ["月报使用期限（天）", "7"], ["月度本地报价来源", "合成来源"]])
        fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.click(screen.getByLabelText(/我独立确认完整月覆盖/));
}
test("monthly opening is read-only and preview independently confirms monthly frequency zero costs", async () => {
    const fetch = mock();
    render(<MonthlyReviewPanel />);
    await fill();
    expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "预览完整月度授权（不保存）" }));
    await screen.findByRole("heading", { name: "完整月度授权预览" });
    const call = fetch.mock.calls.find(([url]) => String(url).endsWith("/preview"));
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ mode: "LOCAL_MONTHLY_REVIEW", frequency: "MONTHLY_AFTER_COMPLETE_CALENDAR_MONTH", monthly_frequency_acknowledgement: true, model_profile_ids: [], data_profile_ids: [], limits: { currency: "NONE", task_tokens: 0, day_tokens: 0, task_cost: "0", day_cost: "0" } });
    expect(screen.getByRole("button", { name: "保存月度授权为暂停" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("月度本地报价来源"), { target: { value: "新来源" } });
    expect(screen.queryByRole("heading", { name: "完整月度授权预览" })).toBeNull();
    expect(screen.getByLabelText(/我独立确认完整月覆盖/)).not.toBeChecked();
});
test("monthly save matches exact preview and remains paused without any mode write", async () => {
    const fetch = mock();
    render(<MonthlyReviewPanel />);
    await fill();
    fireEvent.click(screen.getByRole("button", { name: "预览完整月度授权（不保存）" }));
    await screen.findByRole("heading", { name: "完整月度授权预览" });
    fireEvent.click(screen.getByLabelText(/已核对本次全部月度范围/));
    fireEvent.click(screen.getByRole("button", { name: "保存月度授权为暂停" }));
    await screen.findByText(/月度授权已保存, 默认暂停/);
    const writes = fetch.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(writes).toHaveLength(2);
    expect(JSON.parse(String(writes[1][1]?.body)).preview_hash).toBe("a".repeat(64));
    expect(writes.some(([url]) => String(url).endsWith("/mode"))).toBe(false);
});
test("monthly read failure disables writes with explicit refresh", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("synthetic unavailable"));
    render(<MonthlyReviewPanel />);
    await screen.findByRole("alert");
    await waitFor(() => expect(screen.getByRole("button", { name: "预览完整月度授权（不保存）" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "刷新月度状态与报告" })).toBeEnabled();
});
test("expired frozen replay shows named refusal without stale body or extra write", async () => {
    const fetch = mock(), original = fetch.getMockImplementation()!;
    fetch.mockImplementation(async (url, init) => String(url).endsWith("/history") ? response([{ report_id: "report-a", schedule_id: "schedule", period_start: "2026-10-01", period_end: "2026-10-31", recorded_at: "2026-11-01T00:00:00Z", usable_until: "2026-11-02T00:00:00Z", usable: false, content_hash: "a".repeat(64) }]) : String(url).endsWith("/replay") ? response({ detail: { code: "MONTHLY_REPORT_EXPIRED_HISTORY_PRESERVED", message: "月报已过期, 审计保留" } }, 422) : original(url, init));
    render(<MonthlyReviewPanel />);
    await screen.findByText(/已过期, 仅保留审计历史/);
    fireEvent.click(screen.getByRole("button", { name: "打开月报冻结快照" }));
    await screen.findByRole("alert");
    expect(screen.queryByRole("region", { name: "月报冻结快照" })).toBeNull();
    expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true);
});

test("monthly pagination exposes older authorized and revoked records, reports and tasks", async () => {
    const fetch = mock(), original = fetch.getMockImplementation()!;
    const config = (i: number) => ({ schedule_id: `s${i}`, version: 1, enabled: false, revoked: i === 51, prepared: { command: { name: `月任务${i}`, coverage_start: "2026-10-01", coverage_end: "2026-10-31", quote_source_name: "合成", evidence_source_names: [] }, calendar_source: "合成", calendar_version: "v1", members: [] } });
    const history = (i: number) => ({ report_id: `r${i}`, schedule_id: "s1", period_start: "2026-10-01", period_end: "2026-10-31", recorded_at: "2026-11-01", usable_until: "2026-12-01", usable: true, content_hash: "hash" });
    const task = (i: number) => ({ task_run_id: `t${i}`, status: "FAILED", attempt: 3, error_code: `失败${i}` });
    fetch.mockImplementation(async (url, init) => {
        const path = String(url);
        if (path === "/api/v1/runtime/monthly") return response(Array.from({ length: 50 }, (_, i) => config(i)));
        if (path === "/api/v1/runtime/monthly?offset=50") return response([config(51)]);
        if (path === "/api/v1/runtime/monthly/history") return response(Array.from({ length: 60 }, (_, i) => history(i)));
        if (path === "/api/v1/runtime/monthly/history?offset=60") return response([history(60)]);
        if (path === "/api/v1/runtime/monthly/runs") return response(Array.from({ length: 60 }, (_, i) => task(i)));
        if (path === "/api/v1/runtime/monthly/runs?offset=60") return response([task(60)]);
        return original(url, init);
    });
    render(<MonthlyReviewPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "加载更多月度授权" }));
    await screen.findByRole("heading", { name: /月任务51 · 已永久撤销/ });
    fireEvent.click(screen.getByRole("button", { name: "加载更多月度任务记录" }));
    await screen.findByText(/任务t60/);
    fireEvent.click(screen.getByRole("button", { name: "加载更多月报历史" }));
    await screen.findByText(/报告r60/);
    expect(screen.getByRole("status")).toHaveTextContent("记录同时变化，请刷新");
    expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true);
});

test("monthly pagination failure retains visible records and names a read failure", async () => {
    const fetch = mock(), original = fetch.getMockImplementation()!;
    const config = (i: number) => ({ schedule_id: `s${i}`, version: 1, enabled: false, revoked: false, prepared: { command: { name: `已保留${i}`, coverage_start: "2026-10-01", coverage_end: "2026-10-31", quote_source_name: "合成", evidence_source_names: [] }, calendar_source: "合成", calendar_version: "v1", members: [] } });
    fetch.mockImplementation(async (url, init) => String(url) === "/api/v1/runtime/monthly" ? response(Array.from({ length: 50 }, (_, i) => config(i))) : String(url) === "/api/v1/runtime/monthly?offset=50" ? response({ detail: { code: "SYNTHETIC_FAILURE", message: "读取失败" } }, 503) : original(url, init));
    render(<MonthlyReviewPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "加载更多月度授权" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("加载下一页失败，已有内容保留");
    expect(screen.getByRole("heading", { name: /已保留0/ })).toBeVisible();
    expect(screen.getByRole("button", { name: "加载更多月度授权" })).toBeEnabled();
});
