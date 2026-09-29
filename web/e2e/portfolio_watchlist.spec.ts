import { expect, test } from "@playwright/test";

test("portfolio page creates portfolio and records core/tactical position", async ({
  page,
  request,
}) => {
  await page.goto("/portfolio");
  await expect(page.getByRole("heading", { name: "Portfolio" })).toBeVisible();
  await expect(page.getByText("SIMULATION / NO AUTO TRADE")).toBeVisible();

  const name = "e2e-" + Date.now();
  await page.getByLabel("名称").fill(name);
  await page.getByLabel("基础货币").fill("CNY");
  await page.getByLabel("现金余额").fill("10000");
  await page.getByRole("button", { name: "创建" }).click();
  await expect(page.getByText("组合已创建（未计算市值）")).toBeVisible();

  await page.getByLabel("symbol").fill("600519");
  await page.getByLabel("name").fill("贵州茅台");
  await page.getByLabel("core_quantity").fill("10");
  await page.getByLabel("tactical_quantity").fill("2");
  await page.getByLabel("average_cost").fill("1600");
  await page.getByRole("button", { name: "记录持仓" }).click();
  await expect(page.getByText("持仓已记录（Core/Tactical 分开保存）")).toBeVisible();
  await expect(page.getByRole("cell", { name: "600519" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "10" }).first()).toBeVisible();

  const portfolios = await request.get("/api/v1/portfolios");
  expect(portfolios.ok()).toBeTruthy();
  const list = await portfolios.json();
  const created = list.find((item: { name: string }) => item.name === name);
  expect(created).toBeTruthy();
  expect(created.missing_pricing).toBe(true);
  expect(Array.isArray(created.positions)).toBe(true);
  expect(created.positions.length).toBeGreaterThan(0);
  expect(Number(created.positions[0].core_quantity)).toBe(10);
  expect(Number(created.positions[0].tactical_quantity)).toBe(2);
});

test("csv import blocks commit when invalid rows exist and accepts clean file", async ({
  page,
}) => {
  await page.goto("/portfolio");
  await page.getByLabel("名称").fill("csv-" + Date.now());
  await page.getByRole("button", { name: "创建" }).click();
  await expect(page.getByText("组合已创建（未计算市值）")).toBeVisible();

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
  await expect(page.getByText("可确认导入")).toBeVisible();
  await page.getByRole("button", { name: "确认导入" }).click();
  await expect(page.getByText("CSV 已导入；请对照下表核对持仓")).toBeVisible();
});

test("watchlist shows explicit empty optional fields and supports add/remove", async ({
  page,
}) => {
  await page.goto("/watchlist");
  await expect(page.getByRole("heading", { name: "Watchlist" })).toBeVisible();
  await page.getByLabel("symbol").fill("000001");
  await page.getByLabel("name").fill("平安银行");
  await page.getByRole("button", { name: "加入" }).click();
  await expect(page.getByText("已加入观察清单（缺失状态显示为未提供）")).toBeVisible();
  await expect(page.getByRole("cell", { name: "未提供" }).first()).toBeVisible();
  await page.getByRole("button", { name: "移除" }).click();
  await expect(page.getByText("已移除")).toBeVisible();
});

test("home policy review is read-only and marks TEST_DEFAULT", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Investment Policy/ })).toBeVisible();
  await expect(page.getByText("TEST_DEFAULT", { exact: true }).first()).toBeVisible();
  await expect(
    page.getByText("我已阅读当前政策状态（系统不会在此修改限额）"),
  ).toBeVisible();
});
