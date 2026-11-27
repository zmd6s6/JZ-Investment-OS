import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

const fixture = JSON.parse(readFileSync(new URL("../../.runtime/mvp408-recovery-fixture.json", import.meta.url), "utf8"));
const headers = { Authorization: "Bearer synthetic-weekly-only" };
test.beforeEach(async ({ context }) => {
  await context.addInitScript(() => sessionStorage.setItem("investment_os_write_token", "synthetic-weekly-only"));
});

test("actual CLI Worker week recovers through bounded reads and delayed committed SAVE and mode receipts", async ({ page, request }) => {
  test.setTimeout(90000);
  expect(fixture.report.local_inputs).not.toBeNull();
  expect(fixture.report.phase).toBe("DEGRADED");
  await page.goto("/calendar");
  const panel = page.getByRole("region", { name: "周度组合复核" });
  const card = panel.locator("article").filter({ has: page.getByRole("heading", { name: /合成周度组合复核/ }) });
  await expect(panel).toContainText(`任务${fixture.failed_task.task_run_id} · FAILED · 尝试3`);
  // Read the actual API response, then intentionally withhold delivery beyond
  // the product's 15s deadline. No source or successful response is stubbed.
  await panel.getByLabel("周度任务名称").fill("请求超时仍保留的周草稿");
  let releaseRead!: () => void;
  const heldRead = new Promise<void>(resolve => { releaseRead = resolve; });
  await page.route("**/api/v1/runtime/weekly", async route => {
    if (route.request().method() !== "GET") return route.continue();
    const result = await route.fetch(); expect(result.status()).toBe(200);
    await heldRead;
    await route.fulfill({ response: result }).catch(() => {}); // Caller may already have aborted.
  });
  await panel.getByRole("button", { name: "刷新周度状态与报告" }).click();
  await expect(panel.getByRole("alert")).toContainText("15秒", { timeout: 20000 });
  await expect(panel.getByRole("button", { name: "刷新周度状态与报告" })).toBeEnabled();
  await expect(panel.getByLabel("周度任务名称")).toHaveValue("请求超时仍保留的周草稿");
  await page.unroute("**/api/v1/runtime/weekly");
  await panel.getByRole("button", { name: "刷新周度状态与报告" }).click();
  await expect(card).toBeVisible(); releaseRead();
  const writeBodies: string[] = [];
  page.on("request", req => { if (req.method() === "POST" && req.url().endsWith("/api/v1/runtime/weekly")) writeBodies.push(req.postData()!); });
  await card.getByRole("button", { name: "修订此周度授权" }).click();
  await expect(panel).toContainText("已读取原周度任务当前版本");
  expect(writeBodies).toHaveLength(0);
  await expect(panel.getByLabel("周度组合", { exact: true })).toHaveValue("");
  await expect(panel.getByLabel("周度显式日历", { exact: true })).toHaveValue("");
  await panel.getByLabel("周度组合", { exact: true }).selectOption(fixture.portfolio_id);
  await panel.getByLabel("周度显式日历", { exact: true }).selectOption(fixture.calendar_import_id);
  await panel.getByLabel("逐日完整覆盖清单").fill(fixture.calendar_manifest);
  await panel.getByLabel(/我独立确认完整周覆盖/).check();
  await panel.getByRole("button", { name: "预览完整周度授权（不保存）" }).click();
  await expect(panel.getByRole("heading", { name: "完整周度授权预览" })).toBeVisible();
  expect(writeBodies).toHaveLength(0);
  // A real concurrent command invalidates CAS after preview; preserve the user's draft.
  const before = (await (await request.get("/api/v1/runtime/weekly", { headers })).json())[0];
  const paused = await request.post(`/api/v1/runtime/weekly/${fixture.schedule_id}/mode`, { headers, data: { request_id: crypto.randomUUID(), expected_version: before.version, action: "PAUSE", confirmed: true } });
  expect(paused.ok()).toBeTruthy();
  await panel.getByLabel(/已核对本次全部周度范围/).check();
  await panel.getByRole("button", { name: "保存周度授权为暂停" }).click();
  await expect(panel.getByRole("alert")).toContainText("WEEKLY_VERSION_CONFLICT");
  await expect(panel.getByLabel("周度组合", { exact: true })).toHaveValue(fixture.portfolio_id);
  await panel.getByRole("button", { name: "核对当前版本（保留草稿）" }).click();
  await expect(panel).toContainText("已读取原周度任务当前版本");
  await expect(panel.getByLabel(/我独立确认完整周覆盖/)).not.toBeChecked();
  await panel.getByLabel(/我独立确认完整周覆盖/).check();
  await panel.getByRole("button", { name: "预览完整周度授权（不保存）" }).click();
  await expect(panel.getByRole("heading", { name: "完整周度授权预览" })).toBeVisible();
  await panel.getByLabel(/已核对本次全部周度范围/).check();
  // The production API commits; only delivery is delayed beyond the product's
  // actual deadline. Abort never means the server transaction rolled back.
  let releaseSave!: () => void;
  const heldSave = new Promise<void>(resolve => { releaseSave = resolve; });
  await page.route("**/api/v1/runtime/weekly", async route => {
    if (route.request().method() !== "POST") return route.continue();
    const result = await route.fetch();
    expect(result.status()).toBe(200);
    await heldSave;
    await route.fulfill({ response: result }).catch(() => {});
  });
  await panel.getByRole("button", { name: "保存周度授权为暂停" }).click();
  await expect(panel.getByRole("region", { name: "周度保存结果待核对" })).toBeVisible({ timeout: 20000 });
  await expect(panel.getByRole("alert")).toContainText("服务端可能已经保存");
  await expect(panel.getByLabel("周度本地报价来源")).toBeDisabled();
  await page.unroute("**/api/v1/runtime/weekly");
  await panel.getByRole("button", { name: "刷新周度状态与报告" }).click();
  await expect(card).toContainText("已暂停");
  releaseSave();
  await expect(panel.getByRole("region", { name: "周度保存结果待核对" })).toBeVisible();
  await panel.getByRole("button", { name: "已核对，使用原请求恢复周度保存" }).click();
  await expect(panel).toContainText("周度授权已保存, 默认暂停");
  expect(writeBodies).toHaveLength(3);
  expect(writeBodies[1]).toBe(writeBodies[2]);
  const saved = (await (await request.get("/api/v1/runtime/weekly", { headers })).json())[0];
  expect(saved.schedule_id).toBe(fixture.schedule_id);
  expect(saved.enabled).toBe(false);
  expect((await (await request.get(`/api/v1/runtime/weekly/reports?schedule_id=${fixture.schedule_id}`, { headers })).json()).length).toBe(1);
  // A mode command has the same uncertainty fence and recovers its original
  // request/CAS even after a current-state refresh has observed a newer version.
  const modeBodies: string[] = [];
  page.on("request", req => { if (req.method() === "POST" && req.url().endsWith(`/weekly/${fixture.schedule_id}/mode`)) modeBodies.push(req.postData()!); });
  let releaseMode!: () => void;
  const heldMode = new Promise<void>(resolve => { releaseMode = resolve; });
  await page.route(`**/api/v1/runtime/weekly/${fixture.schedule_id}/mode`, async route => {
    const result = await route.fetch(); expect(result.status()).toBe(200);
    await heldMode; await route.fulfill({ response: result }).catch(() => {});
  });
  await card.getByLabel(/我已核对此保存周度授权/).check();
  await card.getByRole("button", { name: "暂停周度复核" }).click();
  await expect(panel.getByRole("region", { name: "周度启停结果待核对" })).toBeVisible({ timeout: 20000 });
  expect(modeBodies).toHaveLength(1);
  await page.unroute(`**/api/v1/runtime/weekly/${fixture.schedule_id}/mode`);
  await panel.getByRole("button", { name: "刷新周度状态与报告" }).click();
  await expect(card).toContainText("已暂停"); releaseMode();
  await expect(card.getByRole("button", { name: "启用周度复核" })).toBeDisabled();
  await panel.getByRole("button", { name: "已核对，使用原请求恢复周度启停" }).click();
  await expect(panel).toContainText("周度命令已确认并刷新当前状态");
  expect(modeBodies).toHaveLength(2); expect(modeBodies[0]).toBe(modeBodies[1]);
  await card.getByLabel(/我已核对此保存周度授权/).check();
  await card.getByRole("button", { name: "启用周度复核" }).click();
  await expect.poll(async () => (await (await request.get(`/api/v1/runtime/weekly/reports?schedule_id=${fixture.schedule_id}`, { headers })).json()).length, { timeout: 30000 }).toBe(2);
  const reports = await (await request.get(`/api/v1/runtime/weekly/reports?schedule_id=${fixture.schedule_id}`, { headers })).json();
  expect(reports.find((r: {report_id: string}) => r.report_id === fixture.report.report_id)).toEqual(fixture.report);
  const recovered = reports.find((r: {period_start: string}) => r.period_start === fixture.period_start);
  expect(recovered.schedule_id).toBe(fixture.schedule_id);
  expect(recovered.baseline_report_id).toBeNull();
  expect(recovered.phase).toBe("DEGRADED");
  expect(recovered.local_inputs).not.toBeNull();
  const tasks = await (await request.get("/api/v1/runtime/weekly/runs", { headers })).json();
  expect(tasks.find((t: {task_run_id: string}) => t.task_run_id === fixture.failed_task.task_run_id)).toEqual(fixture.failed_task);
  await page.reload();
  await expect(card).toContainText("已启用");
  await expect(panel).toContainText(recovered.report_id);
  await panel.locator("article").filter({ hasText: `报告${recovered.report_id}` }).getByRole("button", { name: "打开周报冻结快照" }).click();
  await expect(panel.getByRole("region", { name: "周报冻结快照" })).toContainText("首次运行, 无可比基线");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "../.runtime/mvp408-recovery-390.png", fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await card.getByLabel(/我已核对此保存周度授权/).check();
  await card.getByRole("button", { name: "永久撤销周度授权" }).click();
  await expect(card).toContainText("已永久撤销");
  await expect(card.getByRole("button", { name: "修订此周度授权" })).toBeDisabled();
  expect((await (await request.get("/api/v1/settings/model-providers", { headers })).json()).length).toBe(0);
  expect((await (await request.get("/api/v1/decision-center", { headers })).json()).length).toBe(0);
});
