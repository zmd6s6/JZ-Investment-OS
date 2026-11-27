import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

const fixture = JSON.parse(readFileSync(new URL("../../.runtime/mvp404-recovery-fixture.json", import.meta.url), "utf8"));
const headers = { Authorization: "Bearer synthetic-monthly-only" };
test.beforeEach(async ({ context }) => {
  await context.addInitScript(() => sessionStorage.setItem("investment_os_write_token", "synthetic-monthly-only"));
});

test("actual CLI Worker month recovers through bounded reads and delayed committed SAVE and mode receipts", async ({ page, request }) => {
  test.setTimeout(90000);
  expect(fixture.report.local_inputs).not.toBeNull();
  expect(fixture.report.phase).toBe("DEGRADED");
  await page.goto("/calendar");
  const panel = page.getByRole("region", { name: "月度组合复核" });
  const card = panel.locator("article").filter({ has: page.getByRole("heading", { name: /合成月度组合复核/ }) });
  await expect(panel).toContainText(`任务${fixture.failed_task.task_run_id} · FAILED · 尝试3`);
  // Read the actual API response, then intentionally withhold delivery beyond
  // the product's 15s deadline. No source or successful response is stubbed.
  await panel.getByLabel("月度任务名称").fill("请求超时仍保留的月草稿");
  let releaseRead!: () => void;
  const heldRead = new Promise<void>(resolve => { releaseRead = resolve; });
  await page.route("**/api/v1/runtime/monthly", async route => {
    if (route.request().method() !== "GET") return route.continue();
    const result = await route.fetch(); expect(result.status()).toBe(200);
    await heldRead;
    await route.fulfill({ response: result }).catch(() => {}); // Caller may already have aborted.
  });
  await panel.getByRole("button", { name: "刷新月度状态与报告" }).click();
  await expect(panel.getByRole("alert")).toContainText("15秒", { timeout: 20000 });
  await expect(panel.getByRole("button", { name: "刷新月度状态与报告" })).toBeEnabled();
  await expect(panel.getByLabel("月度任务名称")).toHaveValue("请求超时仍保留的月草稿");
  await page.setViewportSize({ width: 390, height: 844 });
  await panel.getByRole("alert").screenshot({ path: "../.runtime/mvp404-deadline-get-390.png" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.unroute("**/api/v1/runtime/monthly");
  await panel.getByRole("button", { name: "刷新月度状态与报告" }).click();
  await expect(card).toBeVisible(); releaseRead();
  const writeBodies: string[] = [];
  page.on("request", req => { if (req.method() === "POST" && req.url().endsWith("/api/v1/runtime/monthly")) writeBodies.push(req.postData()!); });
  await card.getByRole("button", { name: "修订此月度授权" }).click();
  await expect(panel).toContainText("已读取原月度任务当前版本");
  expect(writeBodies).toHaveLength(0);
  await expect(panel.getByLabel("月度组合", { exact: true })).toHaveValue("");
  await expect(panel.getByLabel("月度显式日历", { exact: true })).toHaveValue("");
  await panel.getByLabel("月度组合", { exact: true }).selectOption(fixture.portfolio_id);
  await panel.getByLabel("月度显式日历", { exact: true }).selectOption(fixture.calendar_import_id);
  await panel.getByLabel(/我独立确认完整月覆盖/).check();
  await panel.getByRole("button", { name: "预览完整月度授权（不保存）" }).click();
  await expect(panel.getByRole("heading", { name: "完整月度授权预览" })).toBeVisible();
  expect(writeBodies).toHaveLength(0);
  // A real concurrent command invalidates CAS after preview; preserve the user's draft.
  const before = (await (await request.get("/api/v1/runtime/monthly", { headers })).json())[0];
  const paused = await request.post(`/api/v1/runtime/monthly/${fixture.schedule_id}/mode`, { headers, data: { request_id: crypto.randomUUID(), expected_version: before.version, action: "PAUSE", confirmed: true } });
  expect(paused.ok()).toBeTruthy();
  await panel.getByLabel(/已核对本次全部月度范围/).check();
  await panel.getByRole("button", { name: "保存月度授权为暂停" }).click();
  await expect(panel.getByRole("alert")).toContainText("MONTHLY_VERSION_CONFLICT");
  await expect(panel.getByLabel("月度组合", { exact: true })).toHaveValue(fixture.portfolio_id);
  await panel.getByRole("button", { name: "核对当前版本（保留草稿）" }).click();
  await expect(panel).toContainText("已读取原月度任务当前版本");
  await expect(panel.getByLabel(/我独立确认完整月覆盖/)).not.toBeChecked();
  await panel.getByLabel(/我独立确认完整月覆盖/).check();
  await panel.getByRole("button", { name: "预览完整月度授权（不保存）" }).click();
  await expect(panel.getByRole("heading", { name: "完整月度授权预览" })).toBeVisible();
  await panel.getByLabel(/已核对本次全部月度范围/).check();
  // The production API commits; only delivery is delayed beyond the product's
  // actual deadline. Abort never means the server transaction rolled back.
  let releaseSave!: () => void;
  const heldSave = new Promise<void>(resolve => { releaseSave = resolve; });
  await page.route("**/api/v1/runtime/monthly", async route => {
    if (route.request().method() !== "POST") return route.continue();
    const result = await route.fetch();
    expect(result.status()).toBe(200);
    await heldSave;
    await route.fulfill({ response: result }).catch(() => {});
  });
  await panel.getByRole("button", { name: "保存月度授权为暂停" }).click();
  await expect(panel.getByRole("region", { name: "月度保存结果待核对" })).toBeVisible({ timeout: 20000 });
  await expect(panel.getByRole("alert")).toContainText("服务端可能已经保存");
  await expect(panel.getByLabel("月度本地报价来源")).toBeDisabled();
  const recoverSave = panel.getByRole("button", { name: "已核对，使用原请求恢复月度保存" });
  await expect(recoverSave).toBeDisabled();
  await page.setViewportSize({ width: 390, height: 844 });
  await panel.getByRole("region", { name: "月度保存结果待核对" }).screenshot({ path: "../.runtime/mvp404-deadline-unknown-390.png" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.setViewportSize({ width: 1280, height: 720 });
  await recoverSave.dispatchEvent("click");
  expect(writeBodies).toHaveLength(2); // CAS rejection + actual committed save, no recovery POST.
  await page.unroute("**/api/v1/runtime/monthly");
  await page.route("**/api/v1/runtime/monthly", route => route.request().method() === "GET" ? route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "显式合成只读核对失败" }) }) : route.continue());
  await panel.getByRole("button", { name: "刷新月度状态与报告" }).click();
  await expect(panel.getByRole("alert")).toContainText("只读状态加载失败");
  await expect(recoverSave).toBeDisabled(); await recoverSave.dispatchEvent("click");
  expect(writeBodies).toHaveLength(2);
  await page.unroute("**/api/v1/runtime/monthly");
  await panel.getByRole("button", { name: "刷新月度状态与报告" }).click();
  await expect(card).toContainText("已暂停");
  releaseSave();
  await expect(panel.getByRole("region", { name: "月度保存结果待核对" })).toBeVisible();
  await expect(recoverSave).toBeEnabled();
  // Even the same request becoming UNKNOWN again consumes the readback grant.
  let releaseReceipt!: () => void;
  const heldReceipt = new Promise<void>(resolve => { releaseReceipt = resolve; });
  await page.route("**/api/v1/runtime/monthly", async route => {
    if (route.request().method() !== "POST") return route.continue();
    const result = await route.fetch(); expect(result.status()).toBe(200);
    await heldReceipt; await route.fulfill({ response: result }).catch(() => {});
  });
  await recoverSave.click();
  await expect(recoverSave).toBeDisabled();
  await expect(panel.getByRole("button", { name: "刷新月度状态与报告" })).toBeEnabled({ timeout: 20000 });
  await expect(recoverSave).toBeDisabled();
  expect(writeBodies).toHaveLength(3); expect(writeBodies[1]).toBe(writeBodies[2]);
  await page.unroute("**/api/v1/runtime/monthly");
  releaseReceipt();
  await expect(recoverSave).toBeDisabled();
  await panel.getByRole("button", { name: "刷新月度状态与报告" }).click();
  await expect(recoverSave).toBeEnabled();
  await recoverSave.click();
  await expect(panel).toContainText("月度授权已保存, 默认暂停");
  expect(writeBodies).toHaveLength(4);
  expect(writeBodies[1]).toBe(writeBodies[3]);
  const saved = (await (await request.get("/api/v1/runtime/monthly", { headers })).json())[0];
  expect(saved.schedule_id).toBe(fixture.schedule_id);
  expect(saved.enabled).toBe(false);
  expect((await (await request.get(`/api/v1/runtime/monthly/reports?schedule_id=${fixture.schedule_id}`, { headers })).json()).length).toBe(1);
  // A mode command has the same uncertainty fence and recovers its original
  // request/CAS even after a current-state refresh has observed a newer version.
  const modeBodies: string[] = [];
  page.on("request", req => { if (req.method() === "POST" && req.url().endsWith(`/monthly/${fixture.schedule_id}/mode`)) modeBodies.push(req.postData()!); });
  let releaseMode!: () => void;
  const heldMode = new Promise<void>(resolve => { releaseMode = resolve; });
  await page.route(`**/api/v1/runtime/monthly/${fixture.schedule_id}/mode`, async route => {
    const result = await route.fetch(); expect(result.status()).toBe(200);
    await heldMode; await route.fulfill({ response: result }).catch(() => {});
  });
  await card.getByLabel(/我已核对此保存月度授权/).check();
  await card.getByRole("button", { name: "暂停月度复核" }).click();
  await expect(panel.getByRole("region", { name: "月度启停结果待核对" })).toBeVisible({ timeout: 20000 });
  expect(modeBodies).toHaveLength(1);
  const recoverMode = panel.getByRole("button", { name: "已核对，使用原请求恢复月度启停" });
  await expect(recoverMode).toBeDisabled(); await recoverMode.dispatchEvent("click");
  expect(modeBodies).toHaveLength(1);
  await page.unroute(`**/api/v1/runtime/monthly/${fixture.schedule_id}/mode`);
  await page.route("**/api/v1/runtime/monthly", route => route.request().method() === "GET" ? route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "显式合成启停只读核对失败" }) }) : route.continue());
  await panel.getByRole("button", { name: "刷新月度状态与报告" }).click();
  await expect(panel.getByRole("alert")).toContainText("只读状态加载失败");
  await expect(recoverMode).toBeDisabled(); await recoverMode.dispatchEvent("click");
  expect(modeBodies).toHaveLength(1);
  await page.unroute("**/api/v1/runtime/monthly");
  await panel.getByRole("button", { name: "刷新月度状态与报告" }).click();
  await expect(card).toContainText("已暂停"); releaseMode();
  await expect(card.getByRole("button", { name: "启用月度复核" })).toBeDisabled();
  await expect(recoverMode).toBeEnabled(); await recoverMode.click();
  await expect(panel).toContainText("月度命令已确认并刷新当前状态");
  expect(modeBodies).toHaveLength(2); expect(modeBodies[0]).toBe(modeBodies[1]);
  await card.getByLabel(/我已核对此保存月度授权/).check();
  await card.getByRole("button", { name: "启用月度复核" }).click();
  await expect.poll(async () => (await (await request.get(`/api/v1/runtime/monthly/reports?schedule_id=${fixture.schedule_id}`, { headers })).json()).length, { timeout: 30000 }).toBe(2);
  const reports = await (await request.get(`/api/v1/runtime/monthly/reports?schedule_id=${fixture.schedule_id}`, { headers })).json();
  expect(reports.find((r: {report_id: string}) => r.report_id === fixture.report.report_id)).toEqual(fixture.report);
  const recovered = reports.find((r: {period_start: string}) => r.period_start === fixture.period_start);
  expect(recovered.schedule_id).toBe(fixture.schedule_id);
  expect(recovered.baseline_report_id).toBeNull();
  expect(recovered.phase).toBe("DEGRADED");
  expect(recovered.local_inputs).not.toBeNull();
  const tasks = await (await request.get("/api/v1/runtime/monthly/runs", { headers })).json();
  expect(tasks.find((t: {task_run_id: string}) => t.task_run_id === fixture.failed_task.task_run_id)).toEqual(fixture.failed_task);
  await page.reload();
  await expect(card).toContainText("已启用");
  await expect(panel).toContainText(recovered.report_id);
  await panel.locator("article").filter({ hasText: `报告${recovered.report_id}` }).getByRole("button", { name: "打开月报冻结快照" }).click();
  await expect(panel.getByRole("region", { name: "月报冻结快照" })).toContainText("首次运行, 无可比基线");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "../.runtime/mvp404-recovery-390.png", fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await card.getByLabel(/我已核对此保存月度授权/).check();
  await card.getByRole("button", { name: "永久撤销月度授权" }).click();
  await expect(card).toContainText("已永久撤销");
  await expect(card.getByRole("button", { name: "修订此月度授权" })).toBeDisabled();
  expect((await (await request.get("/api/v1/settings/model-providers", { headers })).json()).length).toBe(0);
  expect((await (await request.get("/api/v1/decision-center", { headers })).json()).length).toBe(0);
});
