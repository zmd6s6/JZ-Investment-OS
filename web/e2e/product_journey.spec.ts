import { expect, test } from "@playwright/test";

const WRITE_TOKEN = process.env.INVESTMENT_OS_API_WRITE_TOKEN ?? "e2e-write-token";

for (const width of [390, 800, 1280]) {
  test(`local token remains editable at ${width}px, rejects a wrong value, and verifies with Enter`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/portfolio");
    const opener = page.getByRole("button", { name: "配置写令牌", exact: true });
    await opener.click();
    const dialog = page.getByRole("dialog", { name: "配置本地访问" });
    const input = dialog.getByLabel("写入令牌", { exact: true });
    await expect(input).toBeFocused();
    const bounds = await input.boundingBox();
    expect(bounds!.width).toBeGreaterThan(width === 390 ? 210 : 350);
    await input.pressSequentially("synthetic-incorrect-access");
    await expect(input).toHaveValue("synthetic-incorrect-access");
    await input.press("Enter");
    await expect(dialog.getByRole("alert")).toContainText("写入令牌不正确");
    await expect(input).toHaveValue("synthetic-incorrect-access");
    await input.fill(WRITE_TOKEN);
    await input.press("Enter");
    await expect(dialog).not.toBeVisible();
    await expect(page.getByRole("button", { name: "本地访问已验证" })).toBeVisible();
    await expect(page.getByText(/请重新点击刚才的保存操作/)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.reload();
    await expect(page.getByRole("button", { name: "访问令牌已保存" })).toBeVisible();
    await page.getByRole("button", { name: "访问令牌已保存" }).click();
    await page.getByLabel("写入令牌", { exact: true }).press("Escape");
    await expect(dialog).not.toBeVisible();
  });
}

test("guided portfolio and watchlist journey uses synthetic data and stops before any paid call", async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 900 });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "授权保存 →" })).toBeVisible();
  await page.getByRole("button", { name: "授权保存 →" }).click();
  await page.getByLabel("写入令牌", { exact: true }).fill(WRITE_TOKEN);
  await page.getByRole("button", { name: "验证并保存令牌" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("link", { name: /管理我的持仓/ }).click();
  const name = `合成交互验收-${Date.now()}`;
  await page.getByLabel("组合名称", { exact: true }).fill(name);
  await page.getByRole("button", { name: "创建组合", exact: true }).click();
  await expect(page.getByText("组合已创建", { exact: true })).toBeVisible();
  await page.getByLabel("代码", { exact: true }).fill("688999");
  await page.getByLabel("名称", { exact: true }).fill("合成持仓");
  await page.getByLabel("长期仓数量", { exact: true }).fill("10");
  await page.getByLabel("买入均价", { exact: true }).fill("12.5");
  await page.getByRole("button", { name: "保存持仓", exact: true }).click();
  await expect(page.getByText("持仓已保存", { exact: true })).toBeVisible();
  let analysisCalls = 0;
  await page.route("**/api/v1/analysis-jobs", (route) => { analysisCalls++; return route.fulfill({ status: 503, json: { detail: "synthetic_unavailable" } }); });
  await page.getByRole("button", { name: "立即分析", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("可能调用付费模型");
  await expect(page.getByLabel("分析所用组合")).toHaveValue(await page.evaluate(() => sessionStorage.getItem("selected_portfolio_id")));
  await page.getByRole("button", { name: "暂不分析" }).click();
  expect(analysisCalls).toBe(0);
  await expect(page.getByText(/已载入 688999/)).not.toBeVisible();
  await page.getByRole("link", { name: "观察清单", exact: true }).click();
  await page.getByLabel("代码", { exact: true }).fill("688998");
  await page.getByLabel("名称", { exact: true }).fill("合成观察");
  await page.getByRole("button", { name: "加入清单", exact: true }).click();
  await expect(page.getByText("已加入观察清单", { exact: true })).toBeVisible();
  const row = page.getByRole("row").filter({ hasText: "合成观察" });
  await row.getByRole("button", { name: "立即分析", exact: true }).click();
  await expect(page.getByRole("button", { name: "确认启动分析" })).toBeDisabled();
  await page.getByLabel("分析所用组合").selectOption({ label: `${name} · CNY` });
  await page.getByRole("button", { name: "确认启动分析" }).click();
  await expect(page.getByRole("alert")).toContainText("服务暂时无法完成请求");
  await expect(row).toBeVisible();
  expect(analysisCalls).toBe(1);
});

test("settings guidance and all main routes fit a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  for (const path of ["/", "/portfolio", "/watchlist", "/settings", "/analysis"]) {
    await page.goto(path);
    await expect(page.locator("h1")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
  await page.goto("/settings");
  await page.getByRole("link", { name: "1. 模型与角色", exact: true }).click();
  await expect(page.getByText(/单价按每个 Token 填写/)).toBeVisible();
  await expect(page.getByText(/编辑时留空表示保留现有凭据/)).toBeVisible();
});
