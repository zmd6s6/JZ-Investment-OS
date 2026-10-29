import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
const fixture=JSON.parse(readFileSync(new URL("../../.runtime/mvp205-model-fixture.json",import.meta.url),"utf8"));
const numeric=JSON.parse(readFileSync(new URL("../../.runtime/mvp205-numeric-fixture.json",import.meta.url),"utf8"));
const ids=numeric.ids;
const token="synthetic-mvp205-only";
const headers={Authorization:`Bearer ${token}`};
test.beforeEach(async({context})=>{await context.addInitScript(t=>sessionStorage.setItem("investment_os_write_token",t),token);});
for(const bucket of ["CORE","TACTICAL",""]){
 test(`real API DB Worker UI numeric ${bucket||"missing inputs"} stays shadow`,async({page,request})=>{
  const model=await request.post("/api/v1/settings/model-providers",{headers,data:{name:`205合成模型${bucket||"missing"}-${Date.now()}`,provider_type:"OPENAI_COMPATIBLE",base_url:fixture.base_url,model_name:"synthetic-205",timeout_seconds:30,max_tokens:1000,enabled:true,credential:"synthetic-model-not-real",pricing_version:"synthetic-205",pricing_currency:"CNY",input_token_price:"0",output_token_price:"0",pricing_effective_at:new Date().toISOString()}});
  expect(model.ok()).toBeTruthy();const profile=await model.json();
  expect((await request.put("/api/v1/settings/llm-budget",{headers,data:{version:"synthetic-205",currency:"CNY",task_token_limit:2000000,daily_token_limit:20000000,task_cost_limit:"1",daily_cost_limit:"2"}})).ok()).toBeTruthy();
  await page.goto(`/analysis?portfolio_id=${ids.portfolio}`);
  await expect(page.getByLabel("分析组合")).toHaveValue(ids.portfolio);
  await page.getByLabel("分析标的",{exact:true}).selectOption(ids.instrument);
  await page.getByLabel("统一模型选择").selectOption(profile.id);
  await page.getByLabel("参考行情来源名称").fill("synthetic-205-reference");
  await page.getByLabel(`选择证据 ${ids.evidence}`,{exact:true}).check();
  if(bucket){await page.getByLabel("数值来源快照").selectOption(ids.snapshot);await page.getByLabel("仓位测算分仓").selectOption(bucket);}
  await page.getByLabel(/我同意将本次所选证据/).check();
  const response=page.waitForResponse(r=>r.url().endsWith("/api/v1/analysis/runs")&&r.request().method()==="POST");
  await page.getByRole("button",{name:"明确发起影子分析",exact:true}).click();
  const queued=await(await response).json();
  await expect.poll(async()=>{const r=await request.get(`/api/v1/analysis/runs/${queued.run_id}`);return (await r.json()).status;},{timeout:30000}).toBe("DEGRADED");
  await page.getByRole("button",{name:"刷新运行",exact:true}).click();
  const panel=page.getByRole("region",{name:"确定性风险与仓位"});
  const saved=await(await request.get(`/api/v1/analysis/runs/${queued.run_id}`)).json();
  expect(saved.risk_sizing.risk_gate).toBe(bucket?"PASS":"UNKNOWN");
  expect(saved.risk_sizing.sizing_status).toBe(bucket?"COMPUTED":"BLOCKED");
  expect(saved.shadow_decision.execution_allowed).toBe(false);
  if(bucket){expect(Number(saved.risk_sizing.target_quantity)).toBe(500);expect(Number(saved.risk_sizing.delta_quantity)).toBe(bucket==="CORE"?400:300);await expect(panel.getByText(/目标数量（影子测算）500/)).toBeVisible();await expect(panel.getByText(/单标的上限余量/)).toBeVisible();}
  else {await expect(panel.getByText(/建议数量未提供，不能把缺项显示成0股/)).toBeVisible();await expect(panel.getByText(/未选择具备完整证据的数值来源/)).toBeVisible();}
  expect(await page.getByRole("button",{name:/批准|提交订单/}).count()).toBe(0);
  await page.reload();await page.getByRole("button",{name:new RegExp(queued.run_id.slice(0,8))}).click();
  await expect(page.getByRole("region",{name:"确定性风险与仓位"})).toContainText(bucket?"Sizing COMPUTED":"Sizing BLOCKED");
  await page.screenshot({path:`../.runtime/mvp205-${bucket||"missing"}.png`,fullPage:true});
 });
}
