import { expect, test } from "@playwright/test";

test.skip(process.env.E2E_SYNTHETIC_ANALYSIS !== "1", "仅允许显式隔离的合成后台分析栈");
const token = process.env.INVESTMENT_OS_API_WRITE_TOKEN ?? "synthetic-job-review";
const headers = { Authorization: `Bearer ${token}` };
let portfolioId: string;
let instrumentId: string;
let evidenceTitle: string;

test.beforeAll(async ({ request }) => {
  if (process.env.E2E_BASE_URL !== "http://127.0.0.1:18107") throw new Error("后台分析夹具仅允许命名隔离栈18107");
  const stats = await request.get("/api/v1/test-only/analysis/stats", { headers });
  expect((await stats.json()).mode).toBe("synthetic");
  const portfolio = await request.post("/api/v1/portfolios", { headers, data: { name: `后台合成组合-${Date.now()}`, base_currency: "CNY", cash_balance: "10000" } });
  expect(portfolio.status()).toBe(201); portfolioId = (await portfolio.json()).portfolio_id;
  const identity = await request.post("/api/v1/instruments", { headers, data: { market: "SSE", symbol: "600082", name: "后台合成标的", asset_type: "EQUITY", currency: "CNY", sector: "" } });
  expect(identity.status()).toBe(201); instrumentId = (await identity.json()).instrument_id;
  const now = new Date(Date.now() - 10000).toISOString();
  evidenceTitle = `后台分析合成证据-${Date.now()}`;
  const evidence = await request.post("/api/v1/research/ingest", { headers, data: { provider: "SYNTHETIC", provider_ref: `jobs-${Date.now()}`, artifact_type: "NEWS", instrument_id: instrumentId, source_name: "合成任务资料", source_locator: "https://synthetic.example.test/jobs", source_tier: "OTHER", observed_at: now, effective_at: now, available_at: now, expires_at: null, payload: { title: evidenceTitle, summary: "仅用于隔离浏览器验收" }, source_schema_version: "1.0", supersedes_id: null } });
  expect(evidence.status()).toBe(200);
});

test.beforeEach(async ({ page, request }) => {
  await request.post("/api/v1/test-only/analysis/hold", { headers });
  await page.addInitScript((value) => { sessionStorage.setItem("investment_os_write_token", value); localStorage.setItem("investment_os_guide_open", "false"); }, token);
});
test.afterEach(async ({ request }) => { await request.post("/api/v1/test-only/analysis/release", { headers }); });

async function start(page: import("@playwright/test").Page) {
  await page.goto(`/research?instrument_id=${instrumentId}`);
  await page.getByRole("checkbox", { name: `用于本次分析 ${evidenceTitle}`, exact: true }).check();
  await page.getByRole("button", { name: "选择组合并分析" }).click();
  await page.getByLabel("分析所用组合").selectOption(portfolioId);
  await page.getByRole("button", { name: "确认启动分析" }).click();
  await expect(page).toHaveURL(/\/analysis\?run_id=[0-9a-f-]+$/);
  return new URL(page.url()).searchParams.get("run_id")!;
}

test("real queued run survives navigation and reload, then displays actual stages and report", async ({ page, request }) => {
  const id = await start(page);
  await expect.poll(async () => (await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json()).calls).toBe(5);
  await expect(page.getByRole("heading", { name: "后台任务与真实进度" })).toBeVisible();
  await page.goto("/portfolio");
  await page.goto(`/analysis?run_id=${id}`);
  await expect(page.getByText(/当前阶段：第一轮/)).toBeVisible();
  await page.reload();
  await expect(page.getByText(/当前阶段：第一轮/)).toBeVisible();
  await request.post("/api/v1/test-only/analysis/release", { headers });
  await expect(page.getByRole("heading", { name: "分析详情 · 成功" })).toBeVisible();
  await expect(page.getByText(/最终建议与规则闸门 · 完成/)).toBeVisible();
  await expect(page.getByRole("cell", { name: "fixture-only", exact: false }).first()).toBeVisible();
  expect((await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json()).calls).toBe(8);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

test("cancel confirmation prevents further stages without deleting history", async ({ page, request }) => {
  const id = await start(page);
  await expect.poll(async () => (await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json()).calls).toBe(5);
  await page.getByRole("button", { name: "请求取消", exact: true }).click();
  await expect(page.getByRole("region", { name: "任务操作确认" })).toContainText("可能完成、修复和计费");
  await page.getByRole("button", { name: "确认请求取消" }).click();
  await expect(page.getByText(/取消请求已记录/)).toBeVisible();
  await request.post("/api/v1/test-only/analysis/release", { headers });
  await expect(page.getByRole("heading", { name: "分析详情 · 已取消" })).toBeVisible();
  const record = await (await request.get(`/api/v1/analysis-runs/${id}`, { headers })).json();
  expect(record.payload.input_snapshot.evidence).toHaveLength(1);
  expect((await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json()).calls).toBe(5);
});

test("interrupted work does not replay models; explicit retry creates a linked new run", async ({ page, request }) => {
  const original = await start(page);
  await expect.poll(async () => (await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json()).calls).toBe(5);
  await request.post("/api/v1/test-only/analysis/restart", { headers });
  await expect(page.getByRole("heading", { name: "分析详情 · 失败" })).toBeVisible();
  expect((await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json()).calls).toBe(5);
  await page.getByRole("button", { name: "重新发起新运行" }).click();
  await expect(page.getByRole("region", { name: "任务操作确认" })).toContainText("可能再次计费");
  await page.getByRole("button", { name: "确认新建并调用模型" }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("run_id")).not.toBe(original);
  const next = new URL(page.url()).searchParams.get("run_id")!;
  await request.post("/api/v1/test-only/analysis/release", { headers });
  await expect(page.getByRole("heading", { name: "分析详情 · 成功" })).toBeVisible();
  const old = await (await request.get(`/api/v1/analysis-runs/${original}`, { headers })).json();
  const current = await (await request.get(`/api/v1/analysis-runs/${next}`, { headers })).json();
  expect(old.failure_code).toBe("ANALYSIS_INTERRUPTED");
  expect(current.payload.retry_of).toBe(original);
});
