import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
const fixture = JSON.parse(readFileSync(new URL("../../.runtime/mvp406-browser-fixture.json", import.meta.url), "utf8"));
test.beforeEach(async ({ context }) => { await context.addInitScript(() => sessionStorage.setItem("investment_os_write_token", "synthetic-mvp406-only")); });

test("real Worker reaches the 52nd configuration and UI pages older authorization, pauses and refreshes", async ({ page, request }) => {
  test.setTimeout(180000);
  await expect.poll(async () => {
    const response = await request.get(`/api/v1/runtime/daily/reports?schedule_id=${fixture.tail}`);
    return (await response.json()).length;
  }, { timeout: 150000, intervals: [1000, 2000] }).toBe(1);
  const reports = await (await request.get("/api/v1/runtime/daily/history")).json();
  expect(reports.length).toBe(52);
  await page.goto("/calendar");
  const history = page.getByRole("region", { name: "完整每日历史" });
  await expect(history.getByText(/当前第1条起，本页20条/)).toBeVisible();
  await history.getByRole("button", { name: "加载更多每日历史" }).click();
  await expect(history.getByText(/当前第21条起，本页20条/)).toBeVisible();
  await history.getByRole("button", { name: "加载更多每日历史" }).click();
  await expect(history.getByText(/当前第41条起，本页12条/)).toBeVisible();
  const oldest = history.getByRole("listitem").filter({ hasText: "406合成每日001" });
  await oldest.getByRole("button", { name: "查看此授权" }).click();
  const selected = history.getByRole("article", { name: "所选每日授权" });
  await expect(selected).toContainText(fixture.oldest);
  await expect(selected.getByRole("button", { name: "暂停所选每日授权" })).toBeDisabled();
  await selected.getByRole("checkbox").check();
  await selected.getByRole("button", { name: "暂停所选每日授权" }).click();
  await expect(history.getByRole("status")).toHaveText("已暂停所选每日授权，原历史保留。");
  await page.reload();
  await history.getByLabel("精确每日记录编号").fill(fixture.oldest);
  await history.getByRole("button", { name: "按编号读取每日记录" }).click();
  await expect(history.getByRole("article", { name: "所选每日授权" })).toContainText("已暂停");
  await history.getByLabel("每日历史类别").selectOption("history");
  const first = history.getByRole("listitem").first();
  await first.getByRole("button", { name: "查看此日报" }).click();
  await expect(history.getByRole("article", { name: "所选每日正文" })).toContainText("知识时点");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "../.runtime/mvp406-history.png", fullPage: true });
});

test("daily history read failure clears old controls and explicit refresh recovers", async ({ page }) => {
  await page.goto("/calendar");
  const history = page.getByRole("region", { name: "完整每日历史" });
  await history.getByLabel("精确每日记录编号").fill(fixture.oldest);
  await history.getByRole("button", { name: "按编号读取每日记录" }).click();
  await expect(history.getByRole("article", { name: "所选每日授权" })).toBeVisible();
  await page.route("**/api/v1/runtime/daily?offset=0&limit=20", route => route.abort("failed"));
  await history.getByRole("button", { name: "刷新完整每日历史" }).click();
  await expect(history.getByRole("alert")).toContainText("未确认");
  await expect(history.getByRole("button", { name: "暂停所选每日授权" })).toHaveCount(0);
  await page.unroute("**/api/v1/runtime/daily?offset=0&limit=20");
  await history.getByRole("button", { name: "刷新完整每日历史" }).click();
  await expect(history.getByRole("alert")).toHaveCount(0);
  await expect(history.getByText(/本页20条/)).toBeVisible();
});
