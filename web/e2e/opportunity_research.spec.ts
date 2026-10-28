import { expect, test, APIRequestContext, Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
const token=process.env.E2E_WRITE_TOKEN??'synthetic-mvp203-only';
const headers={Authorization:`Bearer ${token}`};
const fixturePath=new URL('../../.runtime/mvp203-model-fixture.json',import.meta.url);
const stamp=()=>Date.now()+'-'+Math.floor(Math.random()*10000);

async function seed(request:APIRequestContext,model='synthetic-only'){
 const fixture=JSON.parse(readFileSync(fixturePath,'utf8'));
 if(fixture.fixture!=='explicit-synthetic-no-paid-calls'||!fixture.base_url.startsWith('http://127.0.0.1:'))throw new Error('Explicit loopback fixture required; real paid provider forbidden.');
 const id=stamp(),source='合成候选行情'+id;
 let response=await request.post('/api/v1/portfolios',{headers,data:{name:'合成候选组合'+id,base_currency:'CNY',cash_balance:'100'}});expect(response.status()).toBe(201);const book=await response.json();
 response=await request.post('/api/v1/instruments',{headers,data:{market:'SSE',symbol:'SYN402R'+id,name:'合成候选研究'+id,asset_type:'EQUITY',currency:'CNY',sector:'Synthetic'}});expect(response.status()).toBe(201);const target=await response.json();
 const when=new Date(Date.now()-3600000).toISOString(),expires=new Date(Date.now()+86400000).toISOString();
 response=await request.post('/api/v1/market-data/manual-quotes',{headers,data:{request_id:crypto.randomUUID(),instrument_id:target.instrument_id,source_name:source,source_locator:'synthetic://candidate-quote/'+id,currency:'CNY',price:'10',observed_at:when,effective_at:when,available_at:when,expires_at:expires}});expect(response.ok()).toBe(true);const quote=await response.json();
 response=await request.post('/api/v1/opportunities/facts',{headers,data:{request_id:crypto.randomUUID(),instrument_id:target.instrument_id,source_name:'合成候选年报'+id,source_locator:'synthetic://candidate-facts/'+id,observed_at:when,effective_at:when,available_at:when,expires_at:expires,previous_close_at:new Date(Date.now()-86400000).toISOString(),revenue_current:'100',revenue_previous:'80',net_income:'20',annual_diluted_eps:'0.2',previous_close:'8',fiscal_year:new Date().getUTCFullYear()-1,financial_basis:'CALENDAR_YEAR_CONSOLIDATED_CNY',net_income_basis:'ATTRIBUTABLE_TO_ORDINARY_SHAREHOLDERS',quote_evidence_id:quote.evidence_id,same_share_basis:true,suspended:false,industry:'Synthetic'}});expect(response.ok()).toBe(true);
 response=await request.post('/api/v1/opportunities/runs',{headers,data:{request_id:crypto.randomUUID(),instrument_ids:[target.instrument_id],scope_name:'合成单候选'+id,scope_locator:'synthetic://explicit-scope/'+id,quote_source_name:source,fact_source_name:'合成候选年报'+id,as_of:new Date().toISOString(),candidate_limit:1,min_profit_margin:'0.1',min_revenue_growth:'0.1',max_pe:'60',min_price_change:'0'}});expect(response.ok()).toBe(true);const funnel=await response.json();expect(funnel.candidate_ids).toEqual([target.instrument_id]);
 response=await request.post('/api/v1/settings/model-providers',{headers,data:{name:'合成候选模型'+id,provider_type:'OPENAI_COMPATIBLE',base_url:fixture.base_url,model_name:model,timeout_seconds:30,max_tokens:1000,enabled:true,credential:'synthetic-only-no-paid',pricing_version:'synthetic-v1',pricing_currency:'CNY',input_token_price:'0',output_token_price:'0',pricing_effective_at:new Date().toISOString()}});expect(response.ok()).toBe(true);const profile=await response.json();
 response=await request.put('/api/v1/settings/llm-budget',{headers,data:{version:'synthetic-candidate-v1',currency:'CNY',task_token_limit:2000000,daily_token_limit:20000000,task_cost_limit:'1',daily_cost_limit:'2'}});expect(response.ok()).toBe(true);
 return {book,target,funnel,profile};
}
async function open(page:Page,data:Awaited<ReturnType<typeof seed>>){await page.goto(`/opportunities?run_id=${data.funnel.run_id}`);await page.getByRole('button',{name:'准备研究候选 '+data.target.symbol}).click();await expect(page.getByLabel('研究组合')).toBeVisible();await page.getByLabel('研究组合').selectOption(data.book.portfolio_id);await page.getByLabel('候选研究模型').selectOption(data.profile.id);}
test.beforeEach(async({context})=>{await context.addInitScript(value=>sessionStorage.setItem('investment_os_write_token',value),token);});

test('candidate UI explicitly queues one real analysis and retains origin/result on reload',async({page,request},info)=>{
 const data=await seed(request);await open(page,data);
 expect((await(await request.get(`/api/v1/analysis/runs?portfolio_id=${data.book.portfolio_id}`)).json())).toHaveLength(0);
 await expect(page.getByRole('button',{name:'明确发起这一候选研究'})).toBeDisabled();await page.getByLabel(/我确认上述候选Evidence及组合选择/).check();await page.getByRole('button',{name:'明确发起这一候选研究'}).click();await expect(page.getByText(/只读影子结论 AVOID；Risk UNKNOWN \/ Sizing BLOCKED/)).toBeVisible({timeout:25000});
 const history=await(await request.get(`/api/v1/opportunities/runs/${data.funnel.run_id}/research`)).json();expect(history).toHaveLength(1);const result=history[0];expect(result.command.funnel_run_id).toBe(data.funnel.run_id);expect(result.command.analysis.evidence_ids).toEqual(data.funnel.rows[0].evidence_ids);expect(result.analysis_run.status).toBe('DEGRADED');expect(result.analysis_run.steps.filter((step:any)=>step.stage==='MODEL_CALL'&&step.status==='COMPLETED')).toHaveLength(9);expect(result.analysis_run.shadow_decision.execution_allowed).toBe(false);expect(result.analysis_run.shadow_decision.target_quantity).toBeNull();expect((await(await request.get(`/api/v1/analysis/runs?portfolio_id=${data.book.portfolio_id}`)).json())).toHaveLength(1);
 expect(await(await request.get(`/api/v1/opportunities/runs/${data.funnel.run_id}`)).json()).toEqual(data.funnel);
 await page.reload();await page.getByRole('button',{name:'准备研究候选 '+data.target.symbol}).click();await expect(page.getByText(/只读影子结论 AVOID；Risk UNKNOWN \/ Sizing BLOCKED/)).toBeVisible();await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);await page.screenshot({path:info.outputPath('candidate-research-390.png'),fullPage:true});
});

test('invalid required CIO output remains a visible failed linked run without automatic retry',async({page,request})=>{
 const data=await seed(request,'synthetic-invalid-cio');await open(page,data);await page.getByLabel(/我确认上述候选Evidence及组合选择/).check();await page.getByRole('button',{name:'明确发起这一候选研究'}).click();await expect(page.getByText(/研究失败；失败原因 ANALYSIS_REQUIRED_ROLE_INVALID/)).toBeVisible({timeout:25000});const history=await(await request.get(`/api/v1/opportunities/runs/${data.funnel.run_id}/research`)).json();expect(history).toHaveLength(1);expect(history[0].analysis_run.shadow_decision).toBeNull();await page.getByRole('button',{name:'只读刷新候选研究'}).click();expect((await(await request.get(`/api/v1/analysis/runs?portfolio_id=${data.book.portfolio_id}`)).json())).toHaveLength(1);await expect(page.getByLabel(/我确认上述候选Evidence及组合选择/)).not.toBeChecked();
});

test('non-candidate and missing consent are rejected before any candidate request or analysis',async({request})=>{
 const data=await seed(request),choice=await(await request.get(`/api/v1/analysis/choices?instrument_id=${data.target.instrument_id}`)).json();const command={funnel_run_id:data.funnel.run_id,analysis:{request_id:crypto.randomUUID(),portfolio_id:data.book.portfolio_id,instrument_id:crypto.randomUUID(),model_profiles:Object.fromEntries(choice.roles.map((role:string)=>[role,data.profile.id])),evidence_ids:data.funnel.rows[0].evidence_ids,market_source_name:data.funnel.query.quote_source_name,allow_model_calls:true}};
 let response=await request.post('/api/v1/opportunities/research',{headers,data:command});expect(response.status()).toBe(422);expect((await response.json()).detail.code).toBe('NOT_A_BOUNDED_CANDIDATE');
 response=await request.post('/api/v1/opportunities/research',{headers,data:{...command,analysis:{...command.analysis,instrument_id:data.target.instrument_id,allow_model_calls:false}}});expect(response.status()).toBe(422);expect(await(await request.get(`/api/v1/opportunities/runs/${data.funnel.run_id}/research`)).json()).toEqual([]);expect(await(await request.get(`/api/v1/analysis/runs?portfolio_id=${data.book.portfolio_id}`)).json()).toEqual([]);
});
