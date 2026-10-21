import { expect, test } from "@playwright/test";
import { randomInt } from "node:crypto";

test.skip(process.env.E2E_SYNTHETIC_ANALYSIS!=="1","只允许显式隔离的合成分析栈");
const token=process.env.INVESTMENT_OS_API_WRITE_TOKEN??"synthetic-job-review";
const headers={Authorization:`Bearer ${token}`};

async function setup(request: import("@playwright/test").APIRequestContext) {
  if(process.env.E2E_BASE_URL!=="http://127.0.0.1:18107")throw new Error("仅允许合成隔离18107");
  const symbol=String(randomInt(620000,629000));
  const identity=await request.post("/api/v1/instruments",{headers,data:{market:"SSE",symbol,name:`逻辑合成 ${symbol}`,asset_type:"EQUITY",currency:"CNY",sector:""}});
  expect(identity.status()).toBe(201);
  const id=(await identity.json()).instrument_id;
  const now=new Date(Date.now()-10000).toISOString();
  const title=`逻辑合成证据 ${symbol}`;
  expect((await request.post("/api/v1/research/ingest",{headers,data:{provider:"SYNTHETIC",provider_ref:`thesis-${symbol}-${Date.now()}`,artifact_type:"NEWS",instrument_id:id,source_name:"合成逻辑来源",source_locator:`https://synthetic.example.test/${symbol}`,source_tier:"OTHER",observed_at:now,effective_at:now,available_at:now,expires_at:null,payload:{title,summary:"仅用于合成验证"},source_schema_version:"1.0",supersedes_id:null}})).status()).toBe(200);
  return {id,title};
}

test.beforeEach(async({context})=>{
  await context.addInitScript(value=>{sessionStorage.setItem("investment_os_write_token",value);localStorage.setItem("investment_os_guide_open","false");},token);
});

test("human thesis create, revise, reload and feed the frozen version into team analysis",async({page,request})=>{
  const {id,title}=await setup(request);
  await request.post("/api/v1/test-only/analysis/hold",{headers});
  await page.goto(`/research?instrument_id=${id}`);
  await page.getByRole("link",{name:"维护此标的的投资逻辑"}).click();
  await expect(page.getByRole("heading",{name:"投资逻辑工作台"})).toBeVisible();
  await page.getByLabel("长期投资逻辑摘要").fill("合成长期逻辑第一版");
  await page.getByLabel("逻辑支柱 1",{exact:true}).fill("合成产品需求持续");
  await page.getByRole("checkbox",{name:`逻辑支柱 1引用 ${title}`,exact:true}).check();
  await page.getByLabel("逻辑状态",{exact:true}).selectOption("VALID");
  await page.getByRole("button",{name:"保存投资逻辑新版本",exact:true}).click();
  await expect(page.getByText("已保存投资逻辑版本 1，历史未被覆盖。",{exact:true})).toBeVisible();
  await expect(page.getByLabel("长期投资逻辑摘要")).toHaveValue("合成长期逻辑第一版");
  const first=await (await request.get(`/api/v1/theses/${id}/workspace`,{headers})).json();
  expect(first.versions).toHaveLength(1);
  await page.getByLabel("长期投资逻辑摘要").fill("合成长期逻辑第二版");
  await page.getByLabel("逻辑状态",{exact:true}).selectOption("STRENGTHENING");
  await page.getByRole("button",{name:"保存投资逻辑新版本",exact:true}).click();
  await expect(page.getByText("已保存投资逻辑版本 2，历史未被覆盖。",{exact:true})).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("长期投资逻辑摘要")).toHaveValue("合成长期逻辑第二版");
  const changed=await (await request.get(`/api/v1/theses/${id}/workspace`,{headers})).json();
  expect(changed.versions).toHaveLength(2);
  expect(changed.versions[1]).toEqual(first.versions[0]);
  expect(changed.versions[0].semantic_diff.summary_changed).toBe(true);
  expect((await (await request.get("/api/v1/test-only/analysis/stats",{headers})).json()).calls).toBe(0);
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBe(true);
  const portfolio=await request.post("/api/v1/portfolios",{headers,data:{name:`逻辑合成组合-${Date.now()}`,base_currency:"CNY",cash_balance:"10000"}});
  expect(portfolio.status()).toBe(201);
  await page.getByRole("link",{name:"准备资料／继续分析"}).click();
  await page.getByRole("checkbox",{name:`用于本次分析 ${title}`,exact:true}).check();
  await page.getByRole("button",{name:"选择组合并分析"}).click();
  await page.getByLabel("分析所用组合").selectOption((await portfolio.json()).portfolio_id);
  await page.getByRole("button",{name:"确认启动分析"}).click();
  await expect(page).toHaveURL(/\/analysis\?run_id=/);
  await request.post("/api/v1/test-only/analysis/release",{headers});
  await expect(page.getByRole("heading",{name:"分析详情 · 成功"})).toBeVisible();
  await expect(page.getByText("投资逻辑 · 固定版本 2 · 增强",{exact:true})).toBeVisible();
  const stats=await (await request.get("/api/v1/test-only/analysis/stats",{headers})).json();
  expect(stats.thesis_version_ids).toEqual(Array(8).fill(changed.current_version_id));
});

test("stale editor and duplicate save cannot overwrite a new human version",async({page,context,request})=>{
  const {id,title}=await setup(request);
  await page.goto(`/thesis?instrument_id=${id}`);
  await page.getByLabel("长期投资逻辑摘要").fill("合成初始逻辑");
  await page.getByLabel("逻辑支柱 1",{exact:true}).fill("合成初始主张");
  await page.getByRole("checkbox",{name:`逻辑支柱 1引用 ${title}`,exact:true}).check();
  await page.getByRole("button",{name:"保存投资逻辑新版本",exact:true}).click();
  await expect(page.getByText("已保存投资逻辑版本 1，历史未被覆盖。",{exact:true})).toBeVisible();
  const other=await context.newPage();
  await other.goto(`/thesis?instrument_id=${id}`);
  await expect(other.getByLabel("长期投资逻辑摘要")).toHaveValue("合成初始逻辑");
  await page.getByLabel("长期投资逻辑摘要").fill("合成最新逻辑");
  await page.getByRole("button",{name:"保存投资逻辑新版本",exact:true}).click();
  await expect(page.getByText("已保存投资逻辑版本 2，历史未被覆盖。",{exact:true})).toBeVisible();
  await other.getByLabel("长期投资逻辑摘要").fill("迟到的草稿应保留");
  await other.getByRole("button",{name:"保存投资逻辑新版本",exact:true}).click();
  await expect(other.getByText(/本次没有覆盖。输入已保留/)).toBeVisible();
  await expect(other.getByLabel("长期投资逻辑摘要")).toHaveValue("迟到的草稿应保留");
  const workspace=await (await request.get(`/api/v1/theses/${id}/workspace`,{headers})).json();
  expect(workspace.versions).toHaveLength(2);
  expect(workspace.versions[0].content.long_term_summary).toBe("合成最新逻辑");
  await other.close();
});
