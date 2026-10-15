import { expect, test } from "@playwright/test";

const WRITE_TOKEN = process.env.INVESTMENT_OS_API_WRITE_TOKEN ?? "e2e-write-token";

async function authorize(page: import("@playwright/test").Page) {
  await page.addInitScript((token: string) => {
    sessionStorage.setItem("investment_os_write_token", token);
  }, WRITE_TOKEN);
}

const HEADERS = {
  Authorization: `Bearer ${WRITE_TOKEN}`,
  "Content-Type": "application/json",
} as const;

test("portfolio analysis runs end-to-end and the report persists after reload", async ({
  page,
  request,
}) => {
  // Real provider calls (committee + PM + Risk) keep this test well above the
  // default budget; the stage contract requires the full UI acceptance path.
  test.setTimeout(360_000);
  page.setDefaultTimeout(120_000);
  await authorize(page);

  // --- fixture: portfolio + position + synthetic evidence via product APIs ---
  const stamp = Date.now();
  const portfolioRes = await request.post("/api/v1/portfolios", {
    headers: HEADERS,
    data: {
      name: `e2e-analysis-${stamp}`,
      base_currency: "CNY",
      cash_balance: "100000",
    },
  });
  expect(portfolioRes.status()).toBe(201);
  const portfolio = await portfolioRes.json();

  const positionRes = await request.post(
    `/api/v1/portfolios/${portfolio.portfolio_id}/positions`,
    {
      headers: HEADERS,
      data: {
        market: "SSE",
        symbol: "600519",
        name: "贵州茅台",
        asset_type: "EQUITY",
        currency: "CNY",
        sector: "Consumer",
        core_quantity: "10",
        tactical_quantity: "2",
        average_cost: "1600",
        core_reason: "底仓",
        tactical_reason: "波段",
      },
    },
  );
  expect(positionRes.status()).toBe(200);
  const saved = await positionRes.json();
  const instrumentId = saved.positions[0].instrument_id as string;
  expect(instrumentId).toBeTruthy();

  const now = new Date().toISOString();
  for (const [tag, text] of [
    ["macro", "社零同比 +4.8%，白酒批价企稳，消费复苏方向未变。"],
    ["industry", "高端白酒库存周转天数降至 45 天，经销商打款意愿回暖。"],
    ["company", "600519 三季度营收同比 +9.2%，合同负债环比增加 12 亿元。"],
  ]) {
    const evidenceRes = await request.post("/api/v1/research/ingest", {
      headers: HEADERS,
      data: {
        provider: "SYNTHETIC",
        provider_ref: `e2e-analysis-${stamp}-${tag}`,
        artifact_type: "NEWS",
        source_name: "synthetic-provider",
        source_locator: `synthetic://e2e/analysis/${stamp}/${tag}`,
        source_tier: "PRIMARY",
        observed_at: now,
        effective_at: now,
        available_at: now,
        payload: { headline: `E2E 合成材料 ${tag}`, summary: text },
        source_schema_version: "1.0",
        instrument_id: instrumentId,
      },
    });
    expect(evidenceRes.status()).toBe(200);
  }

  // --- UI: open the portfolio page and start the analysis from the position row
  await page.goto("/portfolio");
  await expect(page.getByRole("heading", { name: "我的持仓" })).toBeVisible();
  // Select the API-created portfolio that owns the position.
  await page
    .locator("ul.select-list button")
    .filter({ hasText: `e2e-analysis-${stamp}` })
    .click();
  const row = page.getByRole("row").filter({ hasText: "600519" });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "立即分析" }).click();
  await page.getByRole("button", { name: "确认启动分析" }).click();

  // --- report page: list + detail must render the full chain ---
  await expect(page.getByRole("heading", { name: "分析运行" })).toBeVisible({
    timeout: 300_000,
  });
  const firstDetailButton = page.getByRole("button", { name: "查看" }).first();
  await expect(firstDetailButton).toBeVisible();
  await firstDetailButton.click();

  await expect(page.getByText(/分析详情 · SUCCEEDED|分析详情 · 成功/)).toBeVisible({
    timeout: 120_000,
  });
  // Full committee chain: eight role opinions rendered in the table.
  await expect(page.getByRole("heading", { name: "投资团队意见" })).toBeVisible();
  for (const role of ["MACRO", "FUNDAMENTAL", "RISK", "PORTFOLIO"]) {
    await expect(page.getByRole("cell").filter({ hasText: role }).first()).toBeVisible();
  }
  // Read-only shadow decision banner + pinned policy label.
  await expect(page.getByText("本结果为只读影子分析；批准与执行属于后续阶段")).toBeVisible();
  await expect(page.getByText("TEST_DEFAULT", { exact: true }).first()).toBeVisible();
  // Fail-closed market data: quotes are missing and the limitation is explicit.
  await expect(page.getByText(/MISSING_REFERENCE_QUOTES/).first()).toBeVisible();

  // --- persistence: reload keeps the run readable ---
  await page.reload();
  await expect(page.getByRole("heading", { name: "分析运行" })).toBeVisible();
  await expect(page.getByRole("button", { name: "查看" }).first()).toBeVisible();
  await page.getByRole("button", { name: "查看" }).first().click();
  await expect(page.getByRole("heading", { name: "投资团队意见" })).toBeVisible();
});

test("analysis without evidence fails closed and stays visible after reload", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  await authorize(page);

  const stamp = Date.now();
  const portfolioRes = await request.post("/api/v1/portfolios", {
    headers: HEADERS,
    data: { name: `e2e-noev-${stamp}`, base_currency: "CNY", cash_balance: "50000" },
  });
  expect(portfolioRes.status()).toBe(201);
  const portfolio = await portfolioRes.json();

  const positionRes = await request.post(
    `/api/v1/portfolios/${portfolio.portfolio_id}/positions`,
    {
      headers: HEADERS,
      data: {
        market: "SZSE",
        symbol: "000001",
        name: "平安银行",
        asset_type: "EQUITY",
        currency: "CNY",
        sector: "Finance",
        core_quantity: "100",
        tactical_quantity: "0",
        average_cost: "12",
      },
    },
  );
  expect(positionRes.status()).toBe(200);

  const runRes = await request.post("/api/v1/analysis-runs", {
    headers: HEADERS,
    data: {
      instrument_id: (await positionRes.json()).positions[0].instrument_id,
      portfolio_id: portfolio.portfolio_id,
      source: "PORTFOLIO",
    },
    timeout: 60_000,
  });
  expect(runRes.status()).toBe(201);
  const run = await runRes.json();
  expect(run.status).toBe("FAILED");
  expect(run.failure_code).toBe("INSUFFICIENT_EVIDENCE");

  // The failure must be readable in the product UI and survive a reload.
  await page.goto("/analysis");
  await expect(page.getByRole("heading", { name: "分析运行" })).toBeVisible();
  await page.getByRole("button", { name: "刷新运行列表" }).click();
  const failedPill = page.locator("span.pill.invalid").first();
  await expect(failedPill).toBeVisible();
  await page.getByRole("button", { name: "查看" }).first().click();
  await expect(page.getByText(/分析时点没有可用 Evidence/)).toBeVisible();

  await page.reload();
  await expect(page.locator("span.pill.invalid").first()).toBeVisible();
});
