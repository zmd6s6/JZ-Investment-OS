import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
const fixture = JSON.parse(readFileSync(new URL("../../.runtime/mvp403-model-fixture.json", import.meta.url), "utf8"));
const numeric = JSON.parse(readFileSync(new URL("../../.runtime/mvp403-numeric-fixture.json", import.meta.url), "utf8"));
const headers = { Authorization: "Bearer synthetic-mvp403-only" };
test.beforeEach(async ({ context }) => { await context.addInitScript(() => sessionStorage.setItem("investment_os_write_token", "synthetic-mvp403-only")); });
test("real daily API PG production Worker and Chrome persist local and explicitly authorized shadow reports", async ({ page, request }) => {
    test.setTimeout(240000);
    const due = new Date(Date.now() + 130000);
    const day = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(due);
    const time = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hour12: false }).format(due);
    const previous = await (await request.get("/api/v1/calendar")).json();
    const old = previous.configurations.find((c: {
        venue: string;
    }) => c.venue === "SSE");
    const calendarResponse = await request.post("/api/v1/calendar/imports", { headers, data: { request_id: crypto.randomUUID(), expected_version: old?.version ?? 0, venue: "SSE", source_name: "Synthetic daily explicit close", source_version: `v${Date.now()}`, confirmed_source: true, csv_text: `business_date,close_at\n${day},${time}\n` } });
    expect(calendarResponse.ok(), await calendarResponse.text()).toBeTruthy();
    const calendar = await calendarResponse.json();
    const profileResponse = await request.post("/api/v1/settings/model-providers", { headers, data: { name: `403合成模型-${Date.now()}`, provider_type: "OPENAI_COMPATIBLE", base_url: fixture.base_url, model_name: "synthetic-daily", timeout_seconds: 20, max_tokens: 1000, enabled: true, credential: "synthetic-only-not-real", pricing_version: "synthetic-daily", pricing_currency: "CNY", input_token_price: "0", output_token_price: "0", pricing_effective_at: new Date().toISOString() } });
    expect(profileResponse.ok()).toBeTruthy();
    const profile = await profileResponse.json();
    expect((await request.put("/api/v1/settings/llm-budget", { headers, data: { version: "synthetic-daily", currency: "CNY", task_token_limit: 2000000, daily_token_limit: 20000000, task_cost_limit: "1", daily_cost_limit: "2" } })).ok()).toBeTruthy();
    await page.goto("/calendar");
    await expect(page.getByRole("heading", { name: "每日检查与影子研究" })).toBeVisible();
    await page.getByLabel("组合", { exact: true }).selectOption(numeric.ids.portfolio);
    await page.getByLabel("显式交易日历").selectOption(calendar.import_id);
    await page.getByLabel("完整日期覆盖起日").fill(day);
    await page.getByLabel("完整日期覆盖止日").fill(day);
    const local = async (ts: number) => page.evaluate(t => { const d = new Date(t), pad = (n: number) => String(n).padStart(2, "0"); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`; }, ts);
    await page.getByLabel(/授权开始（浏览器本地时区/).fill(await local(Date.now() - 600000));
    await page.getByLabel("授权截止", { exact: true }).fill(await local(Date.now() + 3600000));
    await page.getByLabel("报告使用期限（天）").fill("7");
    await page.getByLabel("本地报价来源名称").fill("synthetic-205-reference");
    await page.getByLabel(/允许本地资料来源/).fill("205明确合成数值来源");
    const localName = `403本地${Date.now()}`, shadowName = `403影子${Date.now()}`;
    async function saveAndEnable(name: string) {
        await page.getByLabel("任务名称").fill(name);
        await page.getByLabel(/我确认所列组合全体/).check();
        await page.getByRole("button", { name: "预览完整授权（不保存、不启用）" }).click();
        await expect(page.getByRole("heading", { name: "完整授权预览" })).toBeVisible();
        await expect(page.getByRole("button", { name: "保存为暂停（另行启用）" })).toBeDisabled();
        await page.getByLabel(/已核对全部范围/).check();
        const savedResponse = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/runtime/daily");
        await page.getByRole("button", { name: "保存为暂停（另行启用）" }).click();
        const saved = await savedResponse;
        expect(saved.ok()).toBeTruthy();
        const savedConfig = await saved.json();
        const card = page.locator("article").filter({ has: page.getByRole("heading", { name: new RegExp(name) }) });
        await expect(card).toContainText("已暂停");
        await card.getByLabel(/我已核对此保存授权/).check();
        await card.getByRole("button", { name: "启用每日任务" }).click();
        await expect(card).toContainText("已启用");
        return savedConfig.schedule_id as string;
    }
    const localScheduleId = await saveAndEnable(localName);
    await page.getByLabel("运行模式").selectOption("SCHEDULED_SHADOW");
    for (const role of ["宏观", "行业", "基本面", "市场与量化", "事件", "反方", "组合经理", "风险", "投资负责人"])
        await page.getByLabel(`${role}模型`, { exact: true }).selectOption(profile.id);
    for (const [label, value] of [["计费币种", "CNY"], ["单任务Token上限", "2000000"], ["UTC日Token上限", "20000000"], ["单任务费用上限", "1"], ["UTC日费用上限", "2"]])
        await page.getByLabel(label, { exact: true }).fill(value);
    await page.getByLabel(/我明确允许所选模型出站/).check();
    const shadowScheduleId = await saveAndEnable(shadowName);
    await expect.poll(async () => {
        const response = await request.get("/api/v1/runtime/daily/reports");
        const reports = await response.json();
        return reports.some((r: {
            schedule_id: string;
            mode: string;
            phase: string;
            authorization: {
                command: {
                    name: string;
                };
            };
        }) => r.mode === "SCHEDULED_SHADOW" && r.phase === "DEGRADED" && r.schedule_id === shadowScheduleId);
    }, { timeout: 180000, intervals: [2000, 3000] }).toBe(true);
    await page.getByRole("button", { name: "刷新每日状态与报告" }).click();
    await expect(page.getByRole("heading", { name: /需要处理/ }).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: /待处理审批/ }).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: /数据 \/ 任务异常/ }).first()).toBeVisible();
    const reports = await (await request.get("/api/v1/runtime/daily/reports")).json();
    expect(reports.some((r: {
        schedule_id: string;
        mode: string;
        authorization: {
            command: {
                name: string;
            };
        };
    }) => r.mode === "LOCAL_STATUS_ONLY" && r.schedule_id === localScheduleId)).toBeTruthy();
    const shadow = reports.find((r: {
        schedule_id: string;
        mode: string;
        phase: string;
        authorization: {
            command: {
                name: string;
            };
        };
    }) => r.mode === "SCHEDULED_SHADOW" && r.phase === "DEGRADED" && r.schedule_id === shadowScheduleId);
    expect(shadow.hold_watch.analysis_run_ids.length).toBeGreaterThan(0);
    const run = await (await request.get(`/api/v1/analysis/runs/${shadow.hold_watch.analysis_run_ids[0]}`)).json();
    expect(run.shadow_decision.risk_gate).toBe("UNKNOWN");
    expect(run.shadow_decision.execution_allowed).toBe(false);
    await page.reload();
    await expect(page.getByRole("heading", { name: new RegExp(localName) })).toBeVisible();
    const card = page.locator("article").filter({ has: page.getByRole("heading", { name: new RegExp(localName) }) });
    await card.getByLabel(/我已核对此保存授权/).check();
    await card.getByRole("button", { name: "永久撤销授权" }).click();
    await expect(card).toContainText("已永久撤销");
    await expect(card.getByRole("button", { name: "启用每日任务" })).toBeDisabled();
    await page.screenshot({ path: "../.runtime/mvp403-daily-real-chain.png", fullPage: true });
});
test("rejected daily coverage preserves input and creates no authorization or paid queue", async ({ page, request }) => {
    const calendars = await (await request.get("/api/v1/calendar")).json();
    const calendar = calendars.configurations.find((c: {
        venue: string;
    }) => c.venue === "SSE");
    const before = await (await request.get("/api/v1/runtime/daily")).json();
    const runsBefore = await (await request.get(`/api/v1/analysis/runs?portfolio_id=${numeric.ids.portfolio}`)).json();
    await page.goto("/calendar");
    await page.getByLabel("组合", { exact: true }).selectOption(numeric.ids.portfolio);
    await page.getByLabel("显式交易日历").selectOption(calendar.import_id);
    await page.getByLabel("任务名称").fill("403拒绝越界覆盖");
    await page.getByLabel("完整日期覆盖起日").fill("2099-01-01");
    await page.getByLabel("完整日期覆盖止日").fill("2099-01-01");
    const local = async (ts: number) => page.evaluate(t => { const d = new Date(t), pad = (n: number) => String(n).padStart(2, "0"); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`; }, ts);
    await page.getByLabel(/授权开始（浏览器本地时区/).fill(await local(Date.now() - 600000));
    await page.getByLabel("授权截止", { exact: true }).fill(await local(Date.now() + 3600000));
    await page.getByLabel("报告使用期限（天）").fill("7");
    await page.getByLabel("本地报价来源名称").fill("synthetic-205-reference");
    await page.getByLabel(/我确认所列组合全体/).check();
    await page.getByRole("button", { name: "预览完整授权（不保存、不启用）" }).click();
    await expect(page.getByRole("alert")).toContainText("授权边界不满足");
    await expect(page.getByLabel("任务名称")).toHaveValue("403拒绝越界覆盖");
    await expect(page.getByRole("button", { name: "保存为暂停（另行启用）" })).toHaveCount(0);
    expect((await (await request.get("/api/v1/runtime/daily")).json()).length).toBe(before.length);
    expect((await (await request.get(`/api/v1/analysis/runs?portfolio_id=${numeric.ids.portfolio}`)).json()).length).toBe(runsBefore.length);
    await page.screenshot({ path: "../.runtime/mvp403-rejected-coverage.png", fullPage: true });
});
