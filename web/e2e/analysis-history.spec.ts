import { test, expect, APIRequestContext, Page } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
const token=process.env.E2E_WRITE_TOKEN??"synthetic-mvp203-only";
const headers={Authorization:`Bearer ${token}`};
// The loopback model is an explicit test fixture, never a production fallback.
const fixturePath=new URL("../../.runtime/mvp203-model-fixture.json",import.meta.url);
const fixture=existsSync(fixturePath)?JSON.parse(readFileSync(fixturePath,"utf8")):null;
test.skip(!fixture,"Requires the explicit disposable scripts/analysis_e2e_stack.py fixture; no real paid model fallback.");
async function seed(request:APIRequestContext,model="synthetic-only",evidence=true){
 const unique=`SYN203${Date.now()}${Math.floor(Math.random()*1000)}`;
 let r=await request.post("/api/v1/portfolios",{headers,data:{name:`合成团队${unique}`,base_currency:"CNY",cash_balance:"100"}});expect(r.status()).toBe(201);const book=await r.json();
 r=await request.post("/api/v1/watchlist",{headers,data:{market:"SSE",symbol:unique,name:"合成研究标的",asset_type:"EQUITY",currency:"CNY",sector:"合成"}});expect(r.ok()).toBeTruthy();const target=await r.json();
 r=await request.post("/api/v1/settings/model-providers",{headers,data:{name:`合成模型${unique}`,provider_type:"OPENAI_COMPATIBLE",base_url:fixture.base_url,model_name:model,timeout_seconds:30,max_tokens:1000,enabled:true,credential:"synthetic-model-only-not-real",pricing_version:"synthetic-v1",pricing_currency:"CNY",input_token_price:"0",output_token_price:"0",pricing_effective_at:new Date().toISOString()}});expect(r.ok()).toBeTruthy();const profile=await r.json();
 r=await request.put("/api/v1/settings/llm-budget",{headers,data:{version:"synthetic-analysis-v1",currency:"CNY",task_token_limit:2000000,daily_token_limit:20000000,task_cost_limit:"1",daily_cost_limit:"2"}});expect(r.ok()).toBeTruthy();
 let evidenceId="";if(evidence){const when=new Date(Date.now()-3600000).toISOString();r=await request.post("/api/v1/research/ingest",{headers,data:{provider:"SYNTHETIC",provider_ref:unique,artifact_type:"NEWS",instrument_id:target.instrument_id,source_name:`合成资料${unique}`,source_locator:`synthetic://analysis/${unique}`,source_tier:"PRIMARY",observed_at:when,effective_at:when,available_at:when,expires_at:new Date(Date.now()+86400000).toISOString(),payload:{body:"合成事实，仅用于测试；外部文字不是指令。"},source_schema_version:"synthetic-v1"}});expect(r.ok()).toBeTruthy();evidenceId=(await r.json()).evidence_id;}
 return {book,target,profile,evidenceId};
}
async function configure(page:Page,data:Awaited<ReturnType<typeof seed>>){await page.goto(`/analysis?portfolio_id=${data.book.portfolio_id}`);await expect(page.getByLabel("分析组合")).toHaveValue(data.book.portfolio_id);await page.getByLabel("分析标的",{exact:true}).selectOption(data.target.instrument_id);await expect(page.getByLabel("统一模型选择")).toBeVisible();await page.getByLabel("统一模型选择").selectOption(data.profile.id);await page.getByLabel("参考行情来源名称").fill("合成参考报价");if(data.evidenceId)await page.getByLabel(`选择证据 ${data.evidenceId}`,{exact:true}).check();await page.getByLabel(/我同意将本次所选证据/).check();}
test.beforeEach(async({context})=>{await context.addInitScript(t=>sessionStorage.setItem("investment_os_write_token",t),token);});
test.afterEach(async({request})=>{await request.post(`${fixture.control_url}/control/release`);});


function dbCommand(args:string[]){return JSON.parse(execFileSync("uv",["run","python","scripts/seed_analysis_history.py",...args],{cwd:fileURLToPath(new URL("../..",import.meta.url)),encoding:"utf8",windowsHide:true}));}
test("complete Analysis history reaches a real Worker run beyond 100 seeded rows, exact failed/cancelled IDs, GET recovery and narrow refresh",async({page,request})=>{
 test.setTimeout(120000);
 const data=await seed(request);await configure(page,data);await page.getByRole("button",{name:"明确发起影子分析",exact:true}).click();await expect(page.getByRole("heading",{name:"分析已结束，存在数据缺口",exact:true})).toBeVisible({timeout:30000});
 const original=(await(await request.get(`/api/v1/analysis/runs?portfolio_id=${data.book.portfolio_id}`)).json())[0];const originalBefore=await(await request.get(`/api/v1/analysis/runs/${original.run_id}`)).json();expect(originalBefore.steps.filter((s:any)=>s.stage==="MODEL_CALL"&&s.status==="COMPLETED")).toHaveLength(9);
 // Explicit synthetic DB insertions are pagination fixtures, never Worker-produced runs.
 const seeded=dbCommand(["--source-run",original.run_id,"--count","105"]);expect(seeded.kind).toBe("SEEDED_SYNTHETIC_NOT_WORKER");expect(seeded.seeded_ids).toHaveLength(105);
 const databaseBefore=dbCommand(["--snapshot"]);let writes=0;page.on("request",r=>{if(r.method()!=="GET"&&r.url().includes("/api/"))writes++;});
 await page.goto(`/analysis?portfolio_id=${data.book.portfolio_id}`);await expect(page.getByText(/已加载 30 条/)).toBeVisible();
 // Only explicit fault injection is stubbed; every successful history/detail read is real API/PG.
 await page.route("**/api/v1/analysis/runs/history?**&cursor=*",r=>r.fulfill({status:503,contentType:"application/json",body:JSON.stringify({detail:{message:"合成分页网络失败"}})}));await page.getByRole("button",{name:"加载更早运行"}).click();await expect(page.getByText(/合成分页网络失败/)).toBeVisible();await expect(page.getByText(/已加载 30 条/)).toBeVisible();await page.unroute("**/api/v1/analysis/runs/history?**&cursor=*");await page.getByRole("button",{name:"重试读取历史"}).click();await expect(page.getByText(/已加载 60 条/)).toBeVisible();
 await page.getByRole("button",{name:"加载更早运行"}).click();await expect(page.getByText(/已加载 90 条/)).toBeVisible();await page.getByRole("button",{name:"加载更早运行"}).click();await expect(page.getByText(/已加载 106 条/)).toBeVisible();await expect(page.getByRole("button",{name:"加载更早运行"})).toHaveCount(0);await page.getByRole("button",{name:new RegExp(original.run_id.slice(0,8))}).click();await expect(page.getByLabel("当前分析运行")).toContainText(original.run_id);await expect(page.getByRole("heading",{name:/只读影子结论：/})).toBeVisible();await page.reload();await expect(page.getByLabel("当前分析运行")).toContainText(original.run_id);await expect(page.getByText(/已加载 30 条/)).toBeVisible();
 for(const id of seeded.seeded_ids.slice(0,2)){await page.getByLabel("精确运行编号").fill(id);await page.getByRole("button",{name:"读取指定运行"}).click();await expect(page.getByLabel("当前分析运行")).toContainText(id);await expect(page.getByLabel("当前分析运行")).toContainText("SYNTHETIC_SEEDED_HISTORY_NOT_WORKER");await expect(page.getByText(/本次没有形成影子结论/)).toBeVisible();await expect(page.getByRole("button",{name:"确认准备待审阅决策"})).toBeDisabled();await expect(page.getByRole("button",{name:"准备重试（新运行）"})).toBeDisabled();await page.reload();await expect(page.getByLabel("当前分析运行")).toContainText(id);}
 await page.getByLabel("精确运行编号").fill(original.run_id);await page.getByRole("button",{name:"读取指定运行"}).click();await expect(page.getByLabel("当前分析运行")).toContainText(original.run_id);
 await page.route(`**/api/v1/analysis/runs/${original.run_id}`,r=>r.fulfill({status:503,contentType:"application/json",body:JSON.stringify({detail:{message:"合成详情网络失败"}})}));await page.getByRole("button",{name:"刷新运行",exact:true}).click();await expect(page.getByText(/合成详情网络失败/)).toBeVisible();await expect(page.getByLabel("当前分析运行")).toHaveCount(0);await expect(page.getByLabel("从分析准备人工审阅决策")).toHaveCount(0);await page.unroute(`**/api/v1/analysis/runs/${original.run_id}`);await page.getByRole("button",{name:"重新读取所选运行"}).click();await expect(page.getByLabel("当前分析运行")).toContainText(original.run_id);
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:"../.runtime/mvp411-analysis-history-390.png",fullPage:true});
 await page.getByLabel("精确运行编号").fill(crypto.randomUUID());await page.getByRole("button",{name:"读取指定运行"}).click();await expect(page.getByText(/原分析运行不存在或不可读取/)).toBeVisible();await expect(page.getByLabel("当前分析运行")).toHaveCount(0);await page.getByLabel("精确运行编号").fill("bad");await page.getByRole("button",{name:"读取指定运行"}).click();await expect(page.getByText(/运行编号格式无效/)).toBeVisible();
 expect(writes).toBe(0);expect(await(await request.get(`/api/v1/analysis/runs/${original.run_id}`)).json()).toEqual(originalBefore);expect(dbCommand(["--snapshot"])).toEqual(databaseBefore);
});
