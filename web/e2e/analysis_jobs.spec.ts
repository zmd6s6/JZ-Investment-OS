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
test.afterEach(async ({ request }) => { await request.post("/api/v1/test-only/analysis/release", { headers }); await request.post("/api/v1/test-only/analysis/market-release", { headers }); });

async function start(page: import("@playwright/test").Page, modelId?: string, marketNames?: string[], moveUp?: string) {
  await page.goto(`/research?instrument_id=${instrumentId}`);
  await page.getByRole("checkbox", { name: `用于本次分析 ${evidenceTitle}`, exact: true }).check();
  await page.getByRole("button", { name: "选择组合并分析" }).click();
  await page.getByLabel("分析所用组合").selectOption(portfolioId);
  if (modelId) await page.getByLabel("本次分析模型").selectOption(modelId);
  for (const name of marketNames ?? []) await page.getByRole("checkbox", { name: `使用行情源 ${name} · TUSHARE_MARKET`, exact: true }).check();
  if (moveUp) await page.getByRole("button", { name: `上移 ${moveUp}`, exact: true }).click();
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
  await page.getByRole("button", { name: "核对模型前估值快照", exact: true }).click();
  await expect(page.getByText(/模型前上下文已固定/)).toBeVisible();
  const prepared = await (await request.get(`/api/v1/analysis-runs/${id}/execution-context`, { headers })).json();
  expect(prepared.status).toBe("RECORDED");
  expect(prepared.receipt.feature_snapshot_id).toMatch(/^[a-f0-9-]{36}$/);
  await page.reload();
  await expect(page.getByText(/当前阶段：第一轮/)).toBeVisible();
  await request.post("/api/v1/test-only/analysis/release", { headers });
  await expect(page.getByRole("heading", { name: "分析详情 · 成功" })).toBeVisible();
  await expect(page.getByText(/最终建议与规则闸门 · 完成/)).toBeVisible();
  await expect(page.getByRole("cell", { name: "fixture-only", exact: false }).first()).toBeVisible();
  await expect(page.getByText("投资逻辑：未知", { exact: true })).toBeVisible();
  await page.getByRole("button",{name:"查看研究主表记录",exact:true}).click();
  await expect(page.getByText("已保存委员会与风险主表 · 8 项角色运行",{exact:true})).toBeVisible();
  await expect(page.getByText(/正式 Decision 尚未创建/)).toBeVisible();
  const records=await (await request.get(`/api/v1/analysis-runs/${id}/research-records`,{headers})).json();
  expect(records.status).toBe("RECORDED");
  expect(records.risk.gate).toBe("PASS");
  expect(records.agents).toHaveLength(8);
  expect(records.feature_snapshot_id).toBe(prepared.receipt.feature_snapshot_id);
  expect(records.runtime_input_hash).toBe(prepared.receipt.runtime_input_hash);
  await page.getByRole("button",{name:"重新读取研究记录",exact:true}).click();
  expect((await (await request.get(`/api/v1/analysis-runs/${id}/research-records`,{headers})).json())).toEqual(records);
  expect((await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json()).calls).toBe(8);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

test("queued thesis version reaches all agents and remains fixed after a new version and refresh", async ({ page, request }) => {
  const created = await request.post(`/api/v1/test-only/analysis/thesis?instrument_id=${instrumentId}`, { headers });
  expect(created.status()).toBe(200);
  const first = await created.json();
  const id = await start(page);
  const queued = await (await request.get(`/api/v1/analysis-runs/${id}`, { headers })).json();
  expect(queued.payload.input_snapshot.thesis.version.id).toBe(first.id);
  expect(queued.payload.input_snapshot.thesis.effective_state).toBe("VALID");
  const changed = await request.post(`/api/v1/test-only/analysis/thesis?instrument_id=${instrumentId}`, { headers });
  expect(changed.status()).toBe(200);
  expect((await changed.json()).id).not.toBe(first.id);
  await request.post("/api/v1/test-only/analysis/release", { headers });
  await expect(page.getByRole("heading", { name: "分析详情 · 成功" })).toBeVisible();
  await page.getByText(`投资逻辑 · 固定版本 ${first.version} · 有效`, { exact: true }).click();
  await expect(page.getByText(`合成固定逻辑版本 ${first.version}`, { exact: true })).toBeVisible();
  const finished = await (await request.get(`/api/v1/analysis-runs/${id}`, { headers })).json();
  expect(finished.payload.input_snapshot.thesis).toEqual(queued.payload.input_snapshot.thesis);
  expect(finished.payload.decision.thesis_version_id).toBe(first.id);
  const stats = await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json();
  expect(stats.thesis_version_ids).toEqual(Array(8).fill(first.id));
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.reload();
  await expect(page.getByText(`投资逻辑 · 固定版本 ${first.version} · 有效`, { exact: true })).toBeVisible();
  expect((await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json()).calls).toBe(8);
});

test("market ordering controls actual selected sources, records fallback and preserves history", async ({ page, request }) => {
  const names = [`合成空行情-${Date.now()}`, `合成报价行情-${Date.now()}`, `合成未选行情-${Date.now()}`];
  const ids: string[] = [];
  for (const name of names) {
    const created = await request.post("/api/v1/settings/data-providers", { headers, data: { name, provider_type: "TUSHARE_MARKET", base_url: "https://api.tushare.pro", timeout_seconds: 5, enabled: true, retention_days: 30, credential: "synthetic-market-only" } });
    expect(created.status()).toBe(201); ids.push((await created.json()).id);
  }
  // Select backup first, then move primary above it: displayed order must drive execution.
  const held = await request.post(`/api/v1/portfolios/${portfolioId}/positions`, { headers, data: { market: "SSE", symbol: "600082", name: "后台合成标的", asset_type: "EQUITY", currency: "CNY", sector: "合成估值行业", core_quantity: "200", tactical_quantity: "50", average_cost: "10", core_average_cost: "10", tactical_average_cost: "10", core_reason: "合成估值测试", tactical_reason: "合成估值测试" } });
  expect(held.status()).toBe(200);
  const id = await start(page, undefined, [names[1], names[0]], names[0]);
  await request.post("/api/v1/test-only/analysis/release", { headers });
  await expect(page.getByRole("heading", { name: "分析详情 · 成功" })).toBeVisible();
  const run = await (await request.get(`/api/v1/analysis-runs/${id}`, { headers })).json();
  expect(run.payload.input_snapshot.market_plan.profiles.map((p: { profile_id: string }) => p.profile_id)).toEqual(ids.slice(0, 2));
  expect(run.payload.valuation.market_data.attempts.map((p: { status: string }) => p.status)).toEqual(["NO_DATA", "SUCCEEDED"]);
  expect(run.payload.valuation.market_data.attempts[1].quotes[0].reference_price).toBe("12.3456789");
  const exactValue = (value: string) => value.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
  expect(exactValue(run.payload.valuation.nav)).toBe("13086.419725");
  expect(exactValue(run.payload.valuation.position_values[0].core_value)).toBe("2469.13578");
  expect(exactValue(run.payload.valuation.position_values[0].tactical_value)).toBe("617.283945");
  expect(run.payload.sizing.status).toBe("BLOCKED");
  expect(run.payload.sizing.target_quantity).toBeUndefined();
  expect(run.payload.sizing.reason_codes).toContain("VOLATILITY_INPUT_MISSING");
  await expect(page.getByRole("table", { name: "冻结持仓估值明细" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "200 / 50", exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "2469.13578 / 617.283945", exact: true })).toBeVisible();
  await expect(page.getByText("暂不生成建议数量", { exact: true })).toBeVisible();
  const frozenValuation = run.payload.valuation;
  const changed = await request.put(`/api/v1/portfolios/${portfolioId}/cash`, { headers, data: { cash_balance: "20000" } });
  expect(changed.status()).toBe(200);
  expect((await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json()).market_profile_ids).toEqual(ids.slice(0, 2));
  await page.reload();
  await expect(page.getByRole("heading", { name: "行情调用记录", exact: true })).toBeVisible();
  expect((await (await request.get(`/api/v1/analysis-runs/${id}`, { headers })).json()).payload.valuation).toEqual(frozenValuation);
  expect((await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json()).calls).toBe(8);
  await expect(page.getByText(`第 1 档 · ${names[0]}`, { exact: true })).toBeVisible();
  await expect(page.getByText(`第 2 档 · ${names[1]}`, { exact: true })).toBeVisible();
  const events = await (await request.get(`/api/v1/analysis-runs/${id}/market-attempts`, { headers })).json();
  expect(events.map((e: { attempt: { status: string } }) => e.attempt.status)).toEqual(["STARTED", "NO_DATA", "STARTED", "SUCCEEDED"]);
  await expect(page.getByText(/12.3456789 CNY/).first()).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

for (const mode of ["cancel", "interrupt"] as const) {
  test(`market intent survives ${mode} and reload without automatic replay`, async ({ page, request }) => {
    const name = `合成阻塞行情-${mode}-${Date.now()}`;
    const created = await request.post("/api/v1/settings/data-providers", { headers, data: { name, provider_type: "TUSHARE_MARKET", base_url: "https://api.tushare.pro", timeout_seconds: 30, enabled: true, retention_days: 30, credential: "synthetic-market-only" } });
    expect(created.status()).toBe(201);
    const profileId = (await created.json()).id;
    await request.post("/api/v1/test-only/analysis/market-hold", { headers });
    const id = await start(page, undefined, [name]);
    await request.post("/api/v1/test-only/analysis/release", { headers });
    await expect.poll(async () => (await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json()).market_profile_ids).toEqual([profileId]);
    await page.reload();
    await expect(page.getByText(/已保存调用意图，结果未知/)).toBeVisible();
    if (mode === "cancel") {
      await page.getByRole("button", { name: "请求取消", exact: true }).click();
      await page.getByRole("button", { name: "确认请求取消" }).click();
      await request.post("/api/v1/test-only/analysis/market-release", { headers });
      await expect(page.getByRole("heading", { name: "分析详情 · 已取消" })).toBeVisible();
    } else {
      await request.post("/api/v1/test-only/analysis/restart", { headers });
      await expect(page.getByRole("heading", { name: "分析详情 · 失败" })).toBeVisible();
    }
    await page.reload();
    const events = await (await request.get(`/api/v1/analysis-runs/${id}/market-attempts`, { headers })).json();
    expect(events.map((e: { attempt: { status: string } }) => e.attempt.status)).toEqual(mode === "cancel" ? ["STARTED", "SUCCEEDED"] : ["STARTED"]);
    await expect(page.getByText(mode === "cancel" ? /报价齐全；查询/ : /已保存调用意图，结果未知/)).toBeVisible();
    const stats = await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json();
    expect(stats.market_profile_ids).toEqual([profileId]);
    expect(stats.calls).toBe(0); // 行情准备早于模型，取消 / 中断不产生模型调用。
  });
}

test("enabled market profiles remain unused unless explicitly selected", async ({ page, request }) => {
  const id = await start(page);
  await request.post("/api/v1/test-only/analysis/release", { headers });
  await expect(page.getByRole("heading", { name: "分析详情 · 成功" })).toBeVisible();
  await expect(page.getByText(/本次未选择行情源，没有自动调用/)).toBeVisible();
  const run = await (await request.get(`/api/v1/analysis-runs/${id}`, { headers })).json();
  expect(run.payload.input_snapshot.market_plan.profiles).toEqual([]);
  expect(run.payload.valuation.market_data).toEqual({ selection: "NONE", attempts: [] });
  expect((await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json()).market_profile_ids).toEqual([]);
});

test("policy review and historical report expose fixed policy, formula and prompt provenance", async ({ page, request }) => {
  const id = await start(page);
  const queued = await (await request.get(`/api/v1/analysis-runs/${id}`, { headers })).json();
  const governance = queued.payload.input_snapshot.governance;
  expect(governance.policy.mode).toBe("TEST_DEFAULT");
  expect(governance.formula.status).toBe("TEST_DEFAULT");
  expect(governance.strategy_status).toBe("TEST_DEFAULT");
  expect(governance.strategy.status).toBe("DRAFT");
  expect(governance.strategy.mode).toBe("TEST_DEFAULT");
  expect(governance.strategy.id).toMatch(/^[0-9a-f-]{36}$/);
  expect(governance.strategy.code_ref).toMatch(/^sha256:[0-9a-f]{64}$/);
  expect(governance.prompts).toHaveLength(8);
  const review = await (await request.get(`/api/v1/policy/review?portfolio_id=${portfolioId}`, { headers })).json();
  expect(review.snapshot.content_hash).toBe(governance.policy.content_hash);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "投资政策 · 只读审阅" })).toBeVisible();
  await expect(page.getByText("单标的上限（%）", { exact: true })).toBeVisible();
  await request.post("/api/v1/test-only/analysis/release", { headers });
  await page.goto(`/analysis?run_id=${id}`);
  await expect(page.getByRole("heading", { name: "分析详情 · 成功" })).toBeVisible();
  await page.getByText("政策与运行规则版本 · 只读快照", { exact: true }).click();
  await expect(page.getByText("政策：TEST_DEFAULT（工程测试值）", { exact: true })).toBeVisible();
  await expect(page.getByText("宏观 · p6-v3", { exact: true })).toBeVisible();
  await expect(page.getByText(/当前公式仍是 TEST_DEFAULT/)).toBeVisible();
  await expect(page.getByRole("heading", { name: `测试策略 v${governance.strategy.version} · DRAFT（未批准）`, exact: true })).toBeVisible();
  await expect(page.getByText(/策略版本 ID：/)).toContainText(governance.strategy.id);
  await expect(page.getByText(/未激活投资策略/)).toBeVisible();
  const finished = await (await request.get(`/api/v1/analysis-runs/${id}`, { headers })).json();
  expect(finished.payload.input_snapshot.governance).toEqual(governance);
  expect(finished.payload.decision.policy_content_hash).toBe(governance.policy.content_hash);
  const execution = await (await request.get(`/api/v1/analysis-runs/${id}/execution-context`, { headers })).json();
  expect(execution.status).toBe("RECORDED");
  expect(execution.receipt.request_input_hash).toBe(finished.payload.input_snapshot.input_hash);
  expect(finished.payload.context_hash).toBe(execution.receipt.runtime_input_hash);
  expect(finished.payload.context_hash).not.toBe(finished.payload.input_snapshot.input_hash);
  expect(["BUY", "ADD"]).not.toContain(finished.payload.decision.action);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.reload();
  expect((await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json()).calls).toBe(8);
});

test("changed market confirmation is rejected before any model or market call", async ({ page, request }) => {
  const profile = { name: `合成行情冲突-${Date.now()}`, provider_type: "TUSHARE_MARKET", base_url: "https://api.tushare.pro", timeout_seconds: 5, enabled: true, retention_days: 30, credential: "synthetic-market-only" };
  const created = await request.post("/api/v1/settings/data-providers", { headers, data: profile });
  expect(created.status()).toBe(201); const id = (await created.json()).id;
  await page.goto(`/research?instrument_id=${instrumentId}`);
  await page.getByRole("checkbox", { name: `用于本次分析 ${evidenceTitle}`, exact: true }).check();
  await page.getByRole("button", { name: "选择组合并分析" }).click();
  await page.getByLabel("分析所用组合").selectOption(portfolioId);
  await page.getByRole("checkbox", { name: `使用行情源 ${profile.name} · TUSHARE_MARKET`, exact: true }).check();
  expect((await request.put(`/api/v1/settings/data-providers/${id}`, { headers, data: { ...profile, credential: null, enabled: false } })).status()).toBe(200);
  await page.getByRole("button", { name: "确认启动分析" }).click();
  await expect(page.getByRole("alert")).toContainText("行情档案配置已改变或停用，未自动换源");
  const stats = await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json();
  expect(stats.calls).toBe(0); expect(stats.market_profile_ids).toEqual([]);
});

test("explicit per-run model selection survives reload and does not change global role assignments", async ({ page, request }) => {
  const configured = { name: `合成单次模型-${Date.now()}`, provider_type: "OPENAI_COMPATIBLE", base_url: "https://synthetic.example.test/v1", model_name: "fixture-explicit-only", timeout_seconds: 30, max_tokens: 2048, enabled: true, credential: "synthetic-fixture-only", pricing_version: "synthetic-explicit-v1", pricing_currency: "USD", input_token_price: "0.000001", output_token_price: "0.000002" };
  const created = await request.post("/api/v1/settings/model-providers", { headers, data: configured });
  expect(created.status()).toBe(201);
  const modelId = (await created.json()).id;
  const before = await (await request.get("/api/v1/analysis-model-options", { headers })).json();
  const id = await start(page, modelId);
  await expect.poll(async () => (await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json()).calls).toBe(5);
  await request.post("/api/v1/test-only/analysis/release", { headers });
  await expect(page.getByRole("heading", { name: "分析详情 · 成功" })).toBeVisible();
  await page.reload();
  await page.getByText(/本次分析输入快照 · 1 条证据/).click();
  await expect(page.getByText("本次固定的模型与定价", { exact: true })).toBeVisible();
  await expect(page.getByText(/定价版本 synthetic-explicit-v1/).first()).toBeVisible();
  const run = await (await request.get(`/api/v1/analysis-runs/${id}`, { headers })).json();
  expect(run.payload.input_snapshot.model_plan.selected_profile_id).toBe(modelId);
  const stats = await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json();
  expect(stats.calls).toBe(8);
  expect(stats.profile_ids).toEqual(Array(8).fill(modelId));
  const after = await (await request.get("/api/v1/analysis-model-options", { headers })).json();
  expect(after.default_bindings).toEqual(before.default_bindings);
});

test("a changed model configuration requires renewed confirmation before any model call", async ({ page, request }) => {
  const profile = { name: `合成配置冲突-${Date.now()}`, provider_type: "OPENAI_COMPATIBLE", base_url: "https://synthetic.example.test/v1", model_name: "fixture-conflict-only", timeout_seconds: 30, max_tokens: 2048, enabled: true, credential: "synthetic-fixture-only", pricing_version: "synthetic-v1", pricing_currency: "USD", input_token_price: "0.000001", output_token_price: "0.000002" };
  const modelId = (await (await request.post("/api/v1/settings/model-providers", { headers, data: profile })).json()).id;
  await page.goto(`/research?instrument_id=${instrumentId}`);
  await page.getByRole("checkbox", { name: `用于本次分析 ${evidenceTitle}`, exact: true }).check();
  await page.getByRole("button", { name: "选择组合并分析" }).click();
  await page.getByLabel("分析所用组合").selectOption(portfolioId);
  await page.getByLabel("本次分析模型").selectOption(modelId);
  const changed = await request.put(`/api/v1/settings/model-providers/${modelId}`, { headers, data: { ...profile, credential: null, max_tokens: 1024 } });
  expect(changed.status()).toBe(200);
  await page.getByRole("button", { name: "确认启动分析" }).click();
  await expect(page.getByRole("alert")).toContainText("模型或定价配置已改变");
  expect((await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json()).calls).toBe(0);
  await page.getByRole("button", { name: "选择组合并分析" }).click();
  await page.getByLabel("分析所用组合").selectOption(portfolioId);
  await page.getByLabel("本次分析模型").selectOption(modelId);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.getByRole("button", { name: "暂不分析" }).click();
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

test("a stalled history request cannot hide completion and refresh never starts another model run", async ({ page, request }) => {
  let unblock!: () => void;
  const blocked = new Promise<void>((resolve) => { unblock = resolve; });
  let intercepted = false;
  const historyPath = /\/api\/v1\/analysis-runs\/[^/]+\/progress$/;
  await page.route(historyPath, async (route) => {
    if (!intercepted) { intercepted = true; await blocked; }
    await route.continue().catch(() => {}); // The user may have aborted the old read by refreshing.
  });
  try {
    const id = await start(page);
    await expect.poll(async () => (await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json()).calls).toBe(5);
    await expect.poll(() => intercepted).toBe(true);
    await request.post("/api/v1/test-only/analysis/release", { headers });
    await expect(page.getByRole("heading", { name: "分析详情 · 成功" })).toBeVisible();
    await expect(page.getByText("正在读取阶段历史；任务状态独立更新…")).toBeVisible();
    await page.getByRole("button", { name: "刷新任务进度" }).click();
    unblock();
    await expect(page.getByText(/最终建议与规则闸门 · 完成/)).toBeVisible();
    expect((await (await request.get("/api/v1/test-only/analysis/stats", { headers })).json()).calls).toBe(8);
    expect(new URL(page.url()).searchParams.get("run_id")).toBe(id);
  } finally { unblock(); await page.unroute(historyPath); }
});
