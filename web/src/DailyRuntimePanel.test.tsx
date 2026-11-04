import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { DailyRuntimePanel } from "./DailyRuntimePanel";
const response = (v: unknown) => new Response(JSON.stringify(v), { headers: { "Content-Type": "application/json" } });
const book = { portfolio_id: "11111111-1111-4111-8111-111111111111", name: "合成组合", positions: [{ instrument_id: "22222222-2222-4222-8222-222222222222", name: "合成标的", symbol: "600000" }] };
const calendar = { venue: "SSE", import_id: "33333333-3333-4333-8333-333333333333", source_name: "合成日历", source_version: "v1", first_business_date: "2026-11-04", last_business_date: "2026-11-04" };
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function mock() {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
        const u = String(url);
        if (u === "/api/v1/portfolios")
            return response([book]);
        if (u === "/api/v1/watchlist")
            return response([]);
        if (u === "/api/v1/calendar")
            return response({ configurations: [calendar] });
        if (u.includes("analysis/choices"))
            return response({ roles: ["CIO"], models: [] });
        if (u.endsWith("/preview")) {
            const command = JSON.parse(String(init?.body));
            return response({ command, input_hash: "a".repeat(64), calendar_source: "合成日历", calendar_version: "v1", calendar_hash: "b".repeat(64), members: book.positions, models: {}, model_pricing: {}, budget_snapshot: null });
        }
        if (init?.method === "POST")
            return response({ enabled: false });
        return response([]);
    });
}
async function fill() {
    await screen.findByRole("option", { name: "合成组合" });
    fireEvent.change(screen.getByLabelText("任务名称"), { target: { value: "本地每日" } });
    fireEvent.change(screen.getByLabelText("组合"), { target: { value: book.portfolio_id } });
    fireEvent.change(screen.getByLabelText("显式交易日历"), { target: { value: calendar.import_id } });
    for (const [label, value] of [["完整日期覆盖起日", "2026-11-04"], ["完整日期覆盖止日", "2026-11-04"], ["授权开始（浏览器本地时区, 保存为UTC）", "2026-11-04T08:00"], ["授权截止", "2026-11-05T08:00"], ["报告使用期限（天）", "7"], ["本地报价来源名称", "合成报价"]])
        fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.click(screen.getByLabelText(/我确认所列组合全体/));
}
test("daily opening is read-only; preview freezes explicit zero-cost local authorization and edit clears consent", async () => { const fetch = mock(); render(<DailyRuntimePanel />); await fill(); expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true); fireEvent.click(screen.getByRole("button", { name: "预览完整授权（不保存、不启用）" })); await screen.findByRole("heading", { name: "完整授权预览" }); const call = fetch.mock.calls.find(([url]) => String(url).endsWith("/preview")); expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ mode: "LOCAL_STATUS_ONLY", model_profiles: {}, data_profile_ids: [], limits: { currency: "NONE", task_tokens: 0, day_tokens: 0, task_cost: "0", day_cost: "0" } }); expect(screen.getByRole("button", { name: "保存为暂停（另行启用）" })).toBeDisabled(); fireEvent.change(screen.getByLabelText("任务名称"), { target: { value: "修改后" } }); expect(screen.queryByRole("heading", { name: "完整授权预览" })).toBeNull(); });
test("daily save requires separate confirmation and never implicitly enables", async () => { const fetch = mock(); render(<DailyRuntimePanel />); await fill(); fireEvent.click(screen.getByRole("button", { name: "预览完整授权（不保存、不启用）" })); await screen.findByRole("heading", { name: "完整授权预览" }); fireEvent.click(screen.getByLabelText(/已核对全部范围/)); fireEvent.click(screen.getByRole("button", { name: "保存为暂停（另行启用）" })); await screen.findByText(/已保存新授权, 默认暂停/); expect(fetch.mock.calls.filter(([, init]) => init?.method === "POST").length).toBe(2); expect(fetch.mock.calls.some(([url]) => String(url).endsWith("/mode"))).toBe(false); });
test("failed daily read keeps writes unavailable and offers explicit refresh", async () => { vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network")); render(<DailyRuntimePanel />); await screen.findByRole("alert"); await waitFor(() => expect(screen.getByRole("button", { name: "预览完整授权（不保存、不启用）" })).toBeDisabled()); expect(screen.getByRole("button", { name: "刷新每日状态与报告" })).toBeEnabled(); });
test("shadow consent is explicit and validation errors remain editable without an API write", async () => {
    const fetch = mock();
    const implementation = fetch.getMockImplementation()!;
    fetch.mockImplementation(async (url, init) => String(url).includes("analysis/choices") ? response({ roles: ["CIO"], models: [{ profile_id: "model-one", name: "合成模型", model_name: "synthetic", pricing_configured: true }] }) : implementation(url, init));
    render(<DailyRuntimePanel />);
    await fill();
    fireEvent.change(screen.getByLabelText("运行模式"), { target: { value: "SCHEDULED_SHADOW" } });
    await screen.findByRole("option", { name: "合成模型 / synthetic" });
    fireEvent.change(screen.getByLabelText("投资负责人模型"), { target: { value: "model-one" } });
    for (const [label, value] of [["计费币种", "CNY"], ["单任务Token上限", "100"], ["UTC日Token上限", "1000"], ["单任务费用上限", "1"], ["UTC日费用上限", "2"]])
        fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: "预览完整授权（不保存、不启用）" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("明确确认出站和费用");
    expect(fetch.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
    expect(screen.getByLabelText("计费币种")).toBeEnabled();
});
