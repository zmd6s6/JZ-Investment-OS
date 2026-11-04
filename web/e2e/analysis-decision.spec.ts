import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
const model = JSON.parse(readFileSync(new URL("../../.runtime/mvp206-model-fixture.json", import.meta.url), "utf8"));
const fixture = JSON.parse(readFileSync(new URL("../../.runtime/mvp206-numeric-fixture.json", import.meta.url), "utf8"));
const ids = fixture.ids, token = "synthetic-mvp206-only", headers = { Authorization: `Bearer ${token}` };
test.describe.configure({ mode: "serial" });
test.beforeEach(async ({ context }) => { await context.addInitScript(value => sessionStorage.setItem("investment_os_write_token", value), token); });
for (const mode of ["approve-revoke", "reject", "not-frozen"] as const) {
  test(`real API PG Worker Chrome Analysis to explicit Decision ${mode}`, async ({ page, request }) => {
    test.setTimeout(90000);
    const savedProfile = await request.post("/api/v1/settings/model-providers", { headers, data: { name: `206合成模型-${mode}-${Date.now()}`, provider_type: "OPENAI_COMPATIBLE", base_url: model.base_url, model_name: "synthetic-206", timeout_seconds: 30, max_tokens: 1000, enabled: true, credential: "synthetic-only", pricing_version: "synthetic-206", pricing_currency: "CNY", input_token_price: "0", output_token_price: "0", pricing_effective_at: new Date().toISOString() } });
    expect(savedProfile.ok()).toBeTruthy(); const profile = await savedProfile.json();
    expect((await request.put("/api/v1/settings/llm-budget", { headers, data: { version: "synthetic-206", currency: "CNY", task_token_limit: 2000000, daily_token_limit: 20000000, task_cost_limit: "1", daily_cost_limit: "2" } })).ok()).toBeTruthy();
    await page.goto(`/analysis?portfolio_id=${ids.portfolio}`);
    await expect(page.getByLabel("分析组合")).toHaveValue(ids.portfolio);
    await page.getByLabel("分析标的", { exact: true }).selectOption(ids.instrument);
    await page.getByLabel("统一模型选择").selectOption(profile.id);
    await page.getByLabel("参考行情来源名称").fill("synthetic-206-reference");
    await page.getByLabel(`选择证据 ${ids.evidence}`, { exact: true }).check();
    if (mode !== "not-frozen") await page.getByLabel(`选择证据 ${ids.gate_evidence}`, { exact: true }).check();
    await page.getByLabel("数值来源快照").selectOption(ids.snapshot);
    await page.getByLabel("仓位测算分仓").selectOption("CORE");
    await page.getByLabel(/我同意将本次所选证据/).check();
    const queuedResponse = page.waitForResponse(response => response.url().endsWith("/api/v1/analysis/runs") && response.request().method() === "POST");
    await page.getByRole("button", { name: "明确发起影子分析", exact: true }).click();
    const queued = await (await queuedResponse).json();
    await expect.poll(async () => (await (await request.get(`/api/v1/analysis/runs/${queued.run_id}`)).json()).status, { timeout: 60000 }).toBe("DEGRADED");
    await page.getByRole("button", { name: "刷新运行", exact: true }).click();
    const panel = page.getByRole("region", { name: "从分析准备人工审阅决策" });
    await expect(panel.getByRole("button", { name: "确认准备待审阅决策" })).toBeDisabled();
    await panel.getByLabel("原时点固定资格").selectOption(fixture.qualification.qualification_id);
    await panel.getByLabel("准备决策操作者").fill("合成明确准备者");
    await panel.getByLabel(/我确认只准备待审阅记录/).check();
    await panel.getByRole("button", { name: "确认准备待审阅决策" }).click();
    if (mode === "not-frozen") {
      await expect(panel.getByText("已阻断，未创建决策", { exact: false })).toBeVisible();
      await expect(panel.getByText(/资格资料不在本次原始冻结证据内/)).toBeVisible();
      expect(await panel.getByRole("link", { name: "前往决策中心审阅" }).count()).toBe(0);
      await panel.screenshot({ path: "../.runtime/mvp206-blocked-panel.png" });
    } else {
      await panel.getByRole("link", { name: "前往决策中心审阅" }).click();
      const decisionId = new URL(page.url()).searchParams.get("decision_id");
      expect(decisionId).toBeTruthy();
      await expect(page.getByRole("heading", { level: 3, name: /等待明确人工决定/ })).toBeVisible();
      await expect(page.getByText(`Decision ${decisionId}`, { exact: false })).toBeVisible();
      await page.getByLabel("人工归属名称").fill("合成明确人工审阅者");
      await page.getByLabel("本次人工理由").fill("仅在完整合成环境核验固定证据与数量");
      await page.getByLabel(/我已审阅当前版本与风险/).check();
      const action = mode === "reject" ? "reject" : "approve";
      const actionResponse = page.waitForResponse(response => response.url().endsWith(`/${decisionId}/${action}`) && response.request().method() === "POST");
      await page.getByRole("button", { name: mode === "reject" ? "拒绝" : "批准", exact: true }).click();
      const actionSaved = await actionResponse;
      expect(actionSaved.ok()).toBeTruthy();
      expect((await actionSaved.json()).decision.state).toBe(mode === "reject" ? "REJECTED" : "APPROVED");
      if (mode === "approve-revoke") {
        await expect(page.getByRole("heading", { level: 3, name: /已批准，尚未登记成交/ })).toBeVisible();
        await page.getByLabel("本次人工理由").fill("撤销尚未成交的合成人工批准");
        await page.getByLabel(/我已审阅当前版本与风险/).check();
        const revokedResponse = page.waitForResponse(response => response.url().endsWith(`/${decisionId}/revoke`) && response.request().method() === "POST");
        await page.getByRole("button", { name: "撤销未成交批准", exact: true }).click();
        const revoked = await revokedResponse;
        expect(revoked.ok()).toBeTruthy();
        expect((await revoked.json()).decision.state).toBe("CANCELLED");
        await expect(page.getByRole("heading", { level: 3, name: /已撤销/ })).toBeVisible();
      } else await expect(page.getByRole("heading", { level: 3, name: /已拒绝/ })).toBeVisible();
      await page.reload();
      await expect(page.getByRole("heading", { level: 3, name: mode === "reject" ? /已拒绝/ : /已撤销/ })).toBeVisible();
      await expect(page.getByText(`Decision ${decisionId}`, { exact: false })).toBeVisible();
      const persisted = await (await request.get(`/api/v1/decision-center/${decisionId}`)).json();
      expect(persisted.decision.state).toBe(mode === "reject" ? "REJECTED" : "CANCELLED");
      expect(persisted.filled_quantity).toBe("0");
    }
    await page.screenshot({ path: `../.runtime/mvp206-${mode}.png`, fullPage: true });
  });
}
