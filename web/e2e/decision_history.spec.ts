import { expect, test, Page } from "@playwright/test";
import { readFileSync } from "node:fs";
const fixture = JSON.parse(readFileSync(new URL("../../.runtime/mvp407-fixture.json", import.meta.url), "utf8"));
test.beforeEach(async ({ context }) => { await context.addInitScript(() => sessionStorage.setItem("investment_os_write_token", "synthetic-407-only")); });

async function confirm(page: Page) {
  await page.getByLabel("人工归属名称").fill("合成历史审阅者");
  await page.getByLabel("本次人工理由").fill("明确核对原始证据和版本，仅合成工程验收");
  await page.getByLabel(/我已审阅当前版本与风险/).check();
}

test("110 persisted Decisions expose older pages, exact URL, explicit manual fact and immutable refresh", async ({ page, request }) => {
  const older = fixture.older[0];
  const before = await (await request.get(`/api/v1/decision-center/${older}`)).json();
  const first = await (await request.get("/api/v1/decision-center")).json();
  const newestMatching = first.filter((item: { symbol: string }) => item.symbol === "SYNTH301").length;
  const tail = await (await request.get("/api/v1/decision-center?offset=100")).json();
  const tailIndex = tail.findIndex((item: { decision_id: string }) => item.decision_id === older);
  expect(tailIndex).toBeGreaterThanOrEqual(0);
  await page.goto("/decisions");
  await expect(page.getByText(/前 100 条，去重显示 100 条/)).toBeVisible();
  await page.getByRole("button", { name: "加载更早决策" }).click();
  await expect(page.getByText(/前 110 条，去重显示 110 条/)).toBeVisible();
  await page.getByRole("button", { name: /SYNTH301 · BUY/ }).nth(newestMatching + tailIndex).click();
  await expect(page.getByText(`Decision ${older}`, { exact: false })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("decision_id")).toBe(older);
  // Reload the exact original tail even though the new list contains only the first page.
  await page.reload();
  await expect(page.getByText(`Decision ${older}`, { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "批准", exact: true })).toBeDisabled();
  await confirm(page); await page.getByRole("button", { name: "批准", exact: true }).click();
  await expect(page.getByText(/批准已保存，版本 2/)).toBeVisible();
  await page.getByLabel("本次成交数量").fill("1");
  await page.getByLabel("本次成交价格").fill("10");
  await page.getByLabel("本次费用").fill("0.25");
  const time = await page.evaluate(() => { const now = new Date(); return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 23).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, ""); });
  await page.getByLabel("实际成交时间", { exact: true }).fill(time);
  await page.getByLabel("外部成交引用").fill("synthetic-407-manual-reference");
  await page.getByLabel("成交备注").fill("合成已完成事实，不提交真实订单");
  await page.getByLabel(/我已审阅当前版本与风险/).check();
  await page.getByRole("button", { name: "登记外部手工成交事实", exact: true }).click();
  await expect(page.getByText(/登记外部手工成交事实已保存，版本 3/)).toBeVisible();
  await page.reload();
  await expect(page.getByText(/费用 0.25/)).toBeVisible();
  expect(new URL(page.url()).searchParams.get("decision_id")).toBe(older);
  const after = await (await request.get(`/api/v1/decision-center/${older}`)).json();
  expect(after.journal.content_hash).toBe(before.journal.content_hash);
  expect(after.history.map((item: { action: string }) => item.action)).toEqual(["APPROVE", "RECORD_EXECUTION"]);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.locator("section.panel").filter({ has: page.getByRole("heading", { name: "决策详情与审阅", exact: true }) }).screenshot({ path: "../.runtime/mvp407-older-detail.png" });
});

test("older original Decisions preserve explicit rejection, revoke and expired veto legacy refusal", async ({ page }) => {
  await page.goto(`/decisions?decision_id=${fixture.older[1]}`);
  await expect(page.getByRole("button", { name: "批准", exact: true })).toBeDisabled();
  await confirm(page); await page.getByRole("button", { name: "批准", exact: true }).click();
  await expect(page.getByText(/批准已保存/)).toBeVisible();
  await page.getByLabel(/我已审阅当前版本与风险/).check();
  await page.getByRole("button", { name: "撤销未成交批准", exact: true }).click();
  await expect(page.getByText(/撤销未成交批准已保存/)).toBeVisible();
  await page.goto(`/decisions?decision_id=${fixture.older[2]}`);
  await confirm(page); await page.getByRole("button", { name: "拒绝", exact: true }).click();
  await expect(page.getByText(/拒绝已保存/)).toBeVisible();
  for (const key of ["veto", "expired", "policy", "legacy"]) {
    await page.goto(`/decisions?decision_id=${fixture[key]}`);
    await expect(page.getByText(`Decision ${fixture[key]}`, { exact: false })).toBeVisible();
    await expect(page.getByRole("button", { name: "批准", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "登记外部手工成交事实", exact: true })).toHaveCount(0);
  }
});

test("failed older-page read clears actionable detail and explicit refresh recovers exact identity", async ({ page }) => {
  const older = fixture.older[3];
  await page.goto(`/decisions?decision_id=${older}`);
  await confirm(page);
  await expect(page.getByRole("button", { name: "批准", exact: true })).toBeEnabled();
  await page.route("**/api/v1/decision-center?limit=100&offset=100", route => route.abort("failed"));
  await page.getByRole("button", { name: "加载更早决策" }).click();
  await expect(page.getByText(/加载历史失败/)).toBeVisible();
  await expect(page.getByLabel("人工归属名称")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "批准", exact: true })).toHaveCount(0);
  await page.unroute("**/api/v1/decision-center?limit=100&offset=100");
  await page.getByRole("button", { name: "刷新决策列表" }).click();
  await expect(page.getByText(`Decision ${older}`, { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "批准", exact: true })).toBeDisabled();
});

test("an independent exact-ID read survives failure of the newest-list source", async ({ page }) => {
  const older = fixture.older[3];
  await page.route("**/api/v1/decision-center", route => route.abort("failed"));
  await page.goto(`/decisions?decision_id=${older}`);
  await expect(page.getByText(`Decision ${older}`, { exact: false })).toBeVisible();
  await expect(page.getByText(/决策列表读取失败/)).toBeVisible();
  await expect(page.getByRole("button", { name: "批准", exact: true })).toBeDisabled();
  await page.unroute("**/api/v1/decision-center");
  await page.getByRole("button", { name: "刷新决策列表" }).click();
  await expect(page.getByText(/决策列表读取失败/)).toHaveCount(0);
  await expect(page.getByText(`Decision ${older}`, { exact: false })).toBeVisible();
});
