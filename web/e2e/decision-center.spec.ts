import { expect, test, Page, APIRequestContext } from "@playwright/test";
import fs from "node:fs";

const fixture = JSON.parse(fs.readFileSync("../.runtime/mvp301-fixture.json", "utf-8"));
const token = process.env.E2E_WRITE_TOKEN ?? "synthetic-301-only";
test.beforeEach(async ({ context }) => { await context.addInitScript(t => sessionStorage.setItem("investment_os_write_token", t), token); });

async function open(page: Page, request: APIRequestContext, id: string) {
  const response = await request.get("/api/v1/decision-center");
  expect(response.ok()).toBeTruthy();
  const rows = await response.json();
  const index = rows.findIndex((row: { decision_id: string }) => row.decision_id === id);
  expect(index).toBeGreaterThanOrEqual(0);
  await page.goto("/decisions");
  await page.getByRole("button", { name: /SYNTH301 · BUY/ }).nth(index).click();
  await expect(page.getByText(`Decision ${id}`, { exact: false })).toBeVisible();
  await expect(page.locator("p").filter({ hasText: "合成证据支持研究" }).first()).toContainText("引用");
}
async function confirm(page: Page) {
  await page.getByLabel("人工归属名称").fill("synthetic-human");
  await page.getByLabel("本次人工理由").fill("已明确审阅合成证据和固定政策，仅验证工程流程");
  await page.getByLabel(/我已审阅当前版本与风险/).check();
}

test("real production API DB UI explicitly approves and retains complete partial manual facts", async ({ page, request }) => {
  await open(page, request, fixture.decisions[0]);
  await expect(page.getByRole("button", { name: "批准", exact: true })).toBeDisabled();
  await page.evaluate(() => sessionStorage.removeItem("investment_os_write_token"));
  await confirm(page); await page.getByRole("button", { name: "批准", exact: true }).click();
  await expect(page.getByText(/操作未确认/)).toBeVisible();
  await page.evaluate(t => sessionStorage.setItem("investment_os_write_token", t), token);
  await page.getByLabel(/我已审阅当前版本与风险/).check();
  await page.getByRole("button", { name: "批准", exact: true }).click();
  await expect(page.getByText(/批准已保存，版本 2/)).toBeVisible();
  await page.getByLabel("本次成交数量").fill("20");
  await page.getByLabel("本次成交价格").fill("10.01");
  await page.getByLabel("本次费用").fill("1.25");
  const local = await page.evaluate(() => { const now = new Date(); return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 23).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, ""); });
  await page.getByLabel("实际成交时间", { exact: true }).fill(local);
  await page.getByLabel("外部成交引用").fill("synthetic-reference-301");
  await page.getByLabel("成交备注").fill("合成已完成手工事实，无真实交易");
  await page.getByLabel(/我已审阅当前版本与风险/).check();
  await page.getByRole("button", { name: "登记外部手工成交事实", exact: true }).click();
  await expect(page.getByText(/操作未确认/)).toBeVisible();
  await page.getByLabel("本次成交价格").fill("10");
  await page.getByLabel(/我已审阅当前版本与风险/).check();
  await page.getByRole("button", { name: "登记外部手工成交事实", exact: true }).click();
  await expect(page.getByText(/登记外部手工成交事实已保存，版本 3/)).toBeVisible();
  await expect(page.getByText(/费用 1.25/)).toBeVisible();
  await expect(page.getByText(/synthetic-reference-301/)).toBeVisible();
  await page.reload();
  await open(page, request, fixture.decisions[0]);
  await expect(page.getByText(/费用 1.25/)).toBeVisible();
  await expect(page.getByText(/实际成交/).first()).toBeVisible();
  await page.screenshot({ path: "../.runtime/mvp301-manual-history.png", fullPage: true });
});

test("real UI records explicit rejection and revocation without submitting orders", async ({ page, request }) => {
  await open(page, request, fixture.decisions[1]); await confirm(page);
  await page.getByRole("button", { name: "拒绝", exact: true }).click();
  await expect(page.getByText(/拒绝已保存/)).toBeVisible();
  await expect(page.getByRole("button", { name: "批准", exact: true })).toHaveCount(0);
  await open(page, request, fixture.decisions[2]); await confirm(page);
  await page.getByRole("button", { name: "批准", exact: true }).click();
  await expect(page.getByText(/批准已保存/)).toBeVisible();
  await page.getByLabel(/我已审阅当前版本与风险/).check();
  await page.getByRole("button", { name: "撤销未成交批准", exact: true }).click();
  await expect(page.getByText(/撤销未成交批准已保存/)).toBeVisible();
  await page.reload(); await open(page, request, fixture.decisions[2]);
  await expect(page.getByText(/当前没有合法人工操作/)).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByText(/当前.*团队分析.*受限 ShadowDecision/).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2)).toBeTruthy();
});

test("real acceptance and settings navigation expose the assembled record-only center", async ({ page, request }) => {
  const response = await request.get("/api/v1/product-acceptance");
  const snapshot = await response.json();
  const capability = snapshot.capabilities.find((item: { key: string }) => item.key === "decisions");
  expect(capability).toMatchObject({ route: "/decisions", engineering: "PARTIAL", service: "ASSEMBLED", human_acceptance: "PENDING" });
  await page.goto("/settings");
  await page.getByRole("link", { name: "审阅决策与记录人工动作", exact: true }).click();
  await expect(page.getByRole("heading", { name: "决策中心", exact: true })).toBeVisible();
  await expect(page.getByText(/影子结论和失败分析不是待批准交易/)).toHaveCount(0);
});
