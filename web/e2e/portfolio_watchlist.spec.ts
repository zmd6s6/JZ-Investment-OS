import { expect, test } from "@playwright/test";

const WRITE_TOKEN = process.env.INVESTMENT_OS_API_WRITE_TOKEN ?? "e2e-write-token";

async function authorize(page: import("@playwright/test").Page) {
  await page.addInitScript((token: string) => {
    sessionStorage.setItem("investment_os_write_token", token);
  }, WRITE_TOKEN);
}

test("portfolio page creates portfolio and records position with Chinese labels", async ({
  page,
  request,
}) => {
  await authorize(page);
  await page.goto("/portfolio");
  await expect(page.getByRole("heading", { name: "我的持仓" })).toBeVisible();
  await expect(page.getByText("SIMULATION / NO AUTO TRADE")).toBeVisible();

  const name = "e2e-" + Date.now() + "-" + Math.floor(Math.random() * 10000);
  await page.getByLabel("组合名称").fill(name);
  await page.getByLabel("记账货币").selectOption("CNY");
  await page.getByLabel("现金（可选）").fill("10000");
  await page.getByRole("button", { name: "创建组合" }).click();
  await expect(page.getByText("组合已创建")).toBeVisible();

  await page.getByLabel("代码").fill("600519");
  await page.getByLabel("名称", { exact: true }).fill("贵州茅台");
  await page.getByLabel("长期仓数量").fill("10");
  await page.getByLabel("机动仓数量").fill("2");
  await page.getByLabel("买入均价").fill("1600");
  await page.getByLabel("长期仓理由").fill("底仓");
  await page.getByLabel("机动仓理由").fill("波段");
  await page.getByRole("button", { name: "保存持仓" }).click();
  await expect(page.getByText("持仓已保存")).toBeVisible();
  await expect(page.getByRole("cell", { name: "600519" })).toBeVisible();

  const portfolios = await request.get("/api/v1/portfolios");
  expect(portfolios.ok()).toBeTruthy();
  const list = await portfolios.json();
  const created = list.find((item: { name: string }) => item.name === name);
  expect(created).toBeTruthy();
  expect(created.missing_pricing).toBe(true);
  await expect(page.getByRole("cell", { name: "贵州茅台" })).toBeVisible();
});

test("csv import blocks dirty rows and accepts clean file", async ({ page }) => {
  await authorize(page);
  await page.goto("/portfolio");
  await page.getByLabel("组合名称").fill("csv-" + Date.now());
  await page.getByRole("button", { name: "创建组合" }).click();
  await expect(page.getByText("组合已创建")).toBeVisible();

  const header =
    "market,symbol,name,asset_type,currency,sector,core_quantity,tactical_quantity,average_cost";
  const dirty = [header, "SSE,600519,贵州茅台,EQUITY,CNY,Consumer,x,0,1"].join("\n");
  await page.getByLabel("CSV 内容").fill(dirty);
  await page.getByRole("button", { name: "预览" }).click();
  await expect(page.getByText("存在无效行，禁止写入")).toBeVisible();
  await expect(page.getByRole("button", { name: "确认导入" })).toBeDisabled();

  const clean = [header, "SSE,600519,贵州茅台,EQUITY,CNY,Consumer,1,0,1600"].join("\n");
  await page.getByLabel("CSV 内容").fill(clean);
  await page.getByRole("button", { name: "预览" }).click();
  await expect(page.getByText("可以导入", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "确认导入" }).click();
  await expect(page.getByText("已导入", { exact: false }).first()).toBeVisible();
});

test("watchlist is simple add/remove with Chinese empty states", async ({ page }) => {
  await authorize(page);
  await page.goto("/watchlist");
  await expect(page.getByRole("heading", { name: "我在盯的票" })).toBeVisible();
  await page.getByLabel("代码").fill("000001");
  await page.getByLabel("名称").fill("平安银行");
  await page.getByRole("button", { name: "加入清单" }).click();
  await expect(page.getByText("已加入观察清单")).toBeVisible();
  await expect(page.getByRole("cell", { name: "未提供" }).first()).toBeVisible();
  await page.getByRole("button", { name: "移除" }).click();
  await expect(page.getByText(/已移除/)).toBeVisible();
});

test("home policy review is read-only and marks TEST_DEFAULT", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Investment Policy/ })).toBeVisible();
  await expect(page.getByText("TEST_DEFAULT", { exact: true }).first()).toBeVisible();
  await expect(
    page.getByText("我已阅读当前政策状态（系统不会在此修改限额）"),
  ).toBeVisible();
});
