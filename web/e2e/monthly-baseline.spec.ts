import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

const fixture = JSON.parse(readFileSync(new URL("../../.runtime/mvp404-baseline-browser-fixture.json", import.meta.url), "utf8"));
test.beforeEach(async ({ context }) => {
  await context.addInitScript(() => sessionStorage.setItem("investment_os_write_token", "synthetic-monthly-only"));
});

test("real monthly Worker excludes closed captures and preserves the actual comparable report in the browser", async ({ page, request }) => {
  test.setTimeout(90000);
  await page.goto("/calendar");
  await expect(page.getByRole("heading", { name: "周度组合复核", exact: true })).toBeVisible();
  const panel = page.getByRole("region", { name: "月度组合复核" });
  const frozen = panel.getByRole("region", { name: "月报冻结快照" });
  for (const [name, schedule] of Object.entries(fixture.schedules)) {
    const card = panel.locator("article").filter({ has: page.getByRole("heading", { name: new RegExp(name) }) });
    await expect(card).toContainText("已暂停");
    await card.getByLabel(/我已核对此保存月度授权/).check();
    await card.getByRole("button", { name: "启用月度复核" }).click();
    const expectedCount = name === "首次实际捕获" ? 2 : 3;
    await expect.poll(async () => (await (await request.get(`/api/v1/runtime/monthly/reports?schedule_id=${schedule}`)).json()).length, { timeout: 30000 }).toBe(expectedCount);
    const reports = await (await request.get(`/api/v1/runtime/monthly/reports?schedule_id=${schedule}`)).json();
    reports.sort((a: {period_start: string}, b: {period_start: string}) => a.period_start.localeCompare(b.period_start));
    const latest = reports[reports.length - 1], skipped = reports.find((value: {phase: string}) => value.phase === "CLOSED_MONTH_SKIPPED");
    expect(skipped.local_inputs).toBeNull();
    expect(skipped.baseline_report_id).toBeNull();
    expect(skipped.baseline_status).toBe("FIRST_RUN_NO_BASELINE");
    if (name === "首次实际捕获") {
      expect(latest.baseline_report_id).toBeNull();
      expect(latest.baseline_status).toBe("FIRST_RUN_NO_BASELINE");
      expect(latest.holdings[0].core_change).toBeNull();
    } else {
      expect(latest.baseline_report_id).toBe(reports[0].report_id);
      expect(latest.baseline_status).toBe("COMPARABLE_BASELINE");
      expect(latest.evidence_diff.baseline_report_id).toBe(reports[0].report_id);
    }
    await panel.getByRole("button", { name: "刷新月度状态与报告" }).click();
    const historyCard = panel.locator("article").filter({ hasText: `报告${latest.report_id}` });
    await historyCard.getByRole("button", { name: "打开月报冻结快照" }).click();
    await expect(frozen).toContainText(name === "首次实际捕获" ? "首次运行, 无可比基线" : "同授权既往捕获快照");
    if (latest.baseline_report_id) await expect(frozen).toContainText(latest.baseline_report_id);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(frozen).toContainText("SIMULATION / NO AUTO TRADE");
    await page.screenshot({ path: `.runtime/mvp404-baseline-${expectedCount}-reports.png`, fullPage: true });
    for (const original of reports) {
      const replay = await (await request.get(`/api/v1/runtime/monthly/reports/${original.report_id}/replay`)).json();
      expect(replay.content_hash).toBe(original.content_hash);
    }
    await page.reload();
    await expect(card).toContainText("已启用");
    await card.getByLabel(/我已核对此保存月度授权/).check();
    await card.getByRole("button", { name: "暂停月度复核" }).click();
    await expect(card).toContainText("已暂停");
  }
  const rejected = await request.get(`/api/v1/runtime/monthly/reports/${crypto.randomUUID()}/replay`);
  expect(rejected.status()).toBe(422);
  expect((await (await request.get("/api/v1/settings/model-providers")).json()).length).toBe(0);
  expect((await (await request.get("/api/v1/decision-center")).json()).length).toBe(0);
});
