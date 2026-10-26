import { expect, test } from "@playwright/test";

const WRITE_TOKEN = process.env.INVESTMENT_OS_API_WRITE_TOKEN ?? "e2e-write-token";

test("settings explains authorization and saves through the UI without a market token", async ({ page }) => {
  await page.goto("/settings");
  await page.getByRole("button", { name: "保存系统设置", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("尚未配置本系统的写入令牌");
  await page.getByRole("button", { name: "配置写令牌", exact: true }).click();
  await page.getByLabel("写入令牌", { exact: true }).fill(WRITE_TOKEN);
  await page.getByRole("button", { name: "验证并保存令牌", exact: true }).click();
  await expect(page.getByRole("button", { name: "本地访问已验证" })).toBeVisible();
  await page.getByRole("button", { name: "保存系统设置", exact: true }).click();
  await expect(page.getByText("系统设置已保存；自动交易始终关闭。", { exact: true })).toBeVisible();

  const section = page.getByRole("region", { name: "数据 / 研究提供方" });
  const name = `e2e-feedback-${Date.now()}`;
  await section.getByLabel("名称", { exact: true }).fill(name);
  await section.getByLabel("基础 URL", { exact: true }).fill("https://data.example.invalid");
  await section.getByRole("button", { name: "新增数据档案", exact: true }).click();
  await expect(page.getByText("数据提供方档案已保存，尚未启用任何数据同步。", { exact: true })).toBeVisible();
  const card = section.locator("article").filter({ hasText: name });
  await card.getByRole("button", { name: "测试连接", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("未配置此提供方的 API Key");
  await expect(card.getByRole("button", { name: "测试连接", exact: true })).toBeEnabled();
});

test("report reads show progress and recover from failure without losing the run list", async ({ page }) => {
  const run = { id: "synthetic-feedback-run", instrument_id: "synthetic-instrument", portfolio_id: "synthetic-portfolio", source: "PORTFOLIO", status: "SUCCEEDED", policy_version_label: "TEST_DEFAULT", created_at: "2026-10-15T00:00:00Z", as_of: "2026-10-15T00:00:00Z" };
  let release!: () => void;
  const detailPending = new Promise<void>((resolve) => { release = resolve; });
  let detailCalls = 0;
  await page.route("**/api/v1/analysis-runs?*", (route) => route.fulfill({ json: [run] }));
  await page.route("**/api/v1/analysis-runs/synthetic-feedback-run", async (route) => {
    detailCalls++;
    if (detailCalls === 1) {
      await detailPending;
      await route.fulfill({ status: 503, json: { detail: "unavailable" } });
    } else {
      await route.fulfill({ json: { ...run, payload: { opinions: [], failures: ["MISSING_REFERENCE_QUOTES"] } } });
    }
  });
  await page.goto("/analysis");
  await page.getByRole("button", { name: "查看", exact: true }).click();
  await expect(page.getByRole("button", { name: "正在读取…", exact: true })).toBeDisabled();
  release();
  await expect(page.getByText(/服务暂时无法完成请求/)).toBeVisible();
  await page.getByRole("button", { name: "查看", exact: true }).click();
  await expect(page.getByText(/未配置可用行情或未获取到报价/)).toBeVisible();
  expect(detailCalls).toBe(2);
});
