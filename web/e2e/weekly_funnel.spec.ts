import { test, expect, type APIRequestContext, type Page } from '@playwright/test';
const token=process.env.INVESTMENT_OS_API_WRITE_TOKEN??'synthetic-mvp402-only';
const headers={Authorization:`Bearer ${token}`};
// This suite requires scripts/weekly_funnel_e2e_stack.py with 2026-11-02T00:00Z.
// Only the explicitly named disposable _weekly_synthetic DB is used by that harness.
const start='2026-10-26',end='2026-11-01';
const stamp=()=>Date.now()+'-'+Math.floor(Math.random()*100000);
async function checked(response:Awaited<ReturnType<APIRequestContext['post']>>){expect(response.ok(),await response.text()).toBe(true);return response.json();}
async function seed(request:APIRequestContext,missing=false){
 const tag=stamp(),source='合成周报价-'+tag,annual='合成周年报-'+tag;
 const item=await checked(await request.post('/api/v1/instruments',{headers,data:{market:'SSE',symbol:'SYNW'+tag,name:'合成周筛选-'+tag,asset_type:'EQUITY',currency:'CNY',sector:'Synthetic'}}));
 const now=new Date(),past=new Date(now.getTime()-3600000).toISOString(),earlier=new Date(now.getTime()-86400000).toISOString(),expires='2026-11-30T00:00:00Z';
 const quote=await checked(await request.post('/api/v1/market-data/manual-quotes',{headers,data:{request_id:crypto.randomUUID(),instrument_id:item.instrument_id,source_name:source,source_locator:'synthetic://weekly/quote',currency:'CNY',price:'10',observed_at:past,effective_at:past,available_at:past,expires_at:expires}}));
 if(!missing)await checked(await request.post('/api/v1/opportunities/facts',{headers,data:{request_id:crypto.randomUUID(),instrument_id:item.instrument_id,source_name:annual,source_locator:'synthetic://weekly/annual',observed_at:past,effective_at:past,available_at:past,expires_at:expires,revenue_current:'100',revenue_previous:'80',net_income:'20',annual_diluted_eps:'0.2',previous_close:'8',previous_close_at:earlier,fiscal_year:2025,financial_basis:'CALENDAR_YEAR_CONSOLIDATED_CNY',net_income_basis:'ATTRIBUTABLE_TO_ORDINARY_SHAREHOLDERS',quote_evidence_id:quote.evidence_id,same_share_basis:true,suspended:false,industry:'Synthetic',currency:'CNY'}}));
 const run=await checked(await request.post('/api/v1/opportunities/runs',{headers,data:{request_id:crypto.randomUUID(),instrument_ids:[item.instrument_id],scope_name:'合成周有限范围-'+tag,scope_locator:'synthetic://weekly/scope',quote_source_name:source,fact_source_name:annual,as_of:new Date().toISOString(),candidate_limit:1,min_profit_margin:'0.1',min_revenue_growth:'0.1',max_pe:'60',min_price_change:'0'}}));
 return {run,item};
}
async function calendar(request:APIRequestContext,closed=false){
 const status=await (await request.get('/api/v1/calendar')).json();const current=status.configurations.find((c:{venue:string})=>c.venue==='SSE');
 return checked(await request.post('/api/v1/calendar/imports',{headers,data:{request_id:crypto.randomUUID(),expected_version:current?.version??0,venue:'SSE',source_name:'合成完整周日历',source_version:stamp(),csv_text:closed?'business_date,close_at\n2026-10-16,15:00\n2026-11-06,15:00':'business_date,close_at\n2026-10-30,15:00\n2026-11-06,15:00',confirmed_source:true}}));
}
async function save(page:Page,name:string,closed=false){
 await page.getByLabel('周配置名称').fill(name);await page.getByLabel('周筛选市场').selectOption('SSE');await page.getByLabel('完整覆盖开始（周一）').fill(closed?'2026-10-19':start);await page.getByLabel('完整覆盖结束（周日）').fill(closed?'2026-10-25':end);
 await page.getByLabel(/我已核对来源/).check();await page.getByLabel(/仅授权读取/).check();await page.getByRole('button',{name:'保存周配置（暂停）'}).click();await expect(page.getByText(/周筛选新版本已保存，默认暂停/)).toBeVisible();await expect(page.getByText(/周筛选新版本已保存，默认暂停/)).toBeInViewport();
}
async function enable(page:Page,name:string){await page.getByLabel(/我已核对下方保存版本/).check();await page.getByRole('button',{name:'启用本地周筛选 '+name,exact:true}).click();await expect(page.getByText(/已显式启用本地周筛选/)).toBeVisible();}
async function latestTask(request:APIRequestContext,name:string){const o=await (await request.get('/api/v1/opportunities/weekly')).json();const c=o.configurations.find((c:{name:string})=>c.name===name);return o.recent_runs.find((r:{schedule_id:string})=>r.schedule_id===c.schedule_id);}
test.beforeEach(async({page})=>{test.skip(process.env.E2E_BASE_URL!=='http://127.0.0.1:18113','仅MVP402独占weekly_synthetic栈及显式合成时钟，禁止Owner实例');await page.addInitScript(t=>sessionStorage.setItem('investment_os_write_token',t),token);});

test('real API DB Worker UI: paused by default, explicit weekly enable, bounded candidate and durable pause/replay',async({request,page},info)=>{
 const {run,item}=await seed(request);await calendar(request);const name='合成周正常-'+stamp();
 const external:string[]=[];page.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:18113/'))external.push(r.url());});
 await page.goto('/opportunities?run_id='+run.run_id);await expect(page.getByRole('heading',{name:'本次筛选：'+run.query.scope_name})).toBeVisible();await save(page,name);
 const before=await (await request.get('/api/v1/opportunities/weekly')).json();const config=before.configurations.find((c:{name:string})=>c.name===name);expect(config.enabled).toBe(false);expect(before.recent_runs.filter((r:{schedule_id:string})=>r.schedule_id===config.schedule_id)).toHaveLength(0);
 expect(config.template.instrument_ids).toEqual([item.instrument_id]);expect(config.template.candidate_limit).toBe(1);expect(config.paid_calls).toBe(0);
 await enable(page,name);await expect.poll(async()=>{const o=await (await request.get('/api/v1/opportunities/weekly')).json();return o.recent_runs.find((r:{schedule_id:string})=>r.schedule_id===config.schedule_id)?.status;}).toBe('COMPLETE');
 await page.getByRole('button',{name:'刷新周筛选与日历'}).click();
 const result=await (await request.get('/api/v1/opportunities/weekly')).json();const weekly=result.recent_runs.find((r:{schedule_id:string})=>r.schedule_id===config.schedule_id);expect(weekly.as_of).toBe('2026-10-30T07:00:00Z');
 await page.getByRole('button',{name:'暂停 '+name,exact:true}).click();await expect(page.getByText(/暂停已确认/)).toBeVisible();await page.reload();await expect(page.getByRole('heading',{name:name+' · v3 · 已暂停'})).toBeVisible();
 const history=page.locator("article.evidence-card").filter({hasText:weekly.task_run_id});await expect(history.getByText(/候选 1/)).toBeVisible();await history.getByRole('link',{name:'查看本周候选与各层缺项'}).click();await expect(page.getByText(/待深研的研究候选（人工资料未核实）/)).toBeVisible();expect(new URL(page.url()).searchParams.get('run_id')).toBe(weekly.funnel_run_id);expect(external).toEqual([]);
 await page.setViewportSize({width:390,height:844});await expect(page.getByRole('heading',{name:'6 · 每周本地确定性筛选'})).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBe(true);await page.screenshot({path:info.outputPath('weekly-390.png'),fullPage:true});
 const replay=await (await request.get('/api/v1/opportunities/weekly')).json();expect(replay.recent_runs.filter((r:{schedule_id:string})=>r.schedule_id===config.schedule_id)).toHaveLength(1);
});

test('real local missing facts produce visible degraded result and never automatic research',async({page,request})=>{
 const {run}=await seed(request,true);await calendar(request);const name='合成周缺项-'+stamp();await page.goto('/opportunities?run_id='+run.run_id);await save(page,name);await enable(page,name);
 await expect.poll(async()=>{const o=await (await request.get('/api/v1/opportunities/weekly')).json();const c=o.configurations.find((c:{name:string})=>c.name===name);return o.recent_runs.find((r:{schedule_id:string})=>r.schedule_id===c?.schedule_id)?.status;}).toBe('DEGRADED');
 await page.getByRole('button',{name:'刷新周筛选与日历'}).click();const task=await latestTask(request,name);await expect(page.locator('article.evidence-card').filter({hasText:task.task_run_id}).getByText(/本地资料缺失、到期或在业务时点不可用/)).toBeVisible();await page.getByRole('button',{name:'暂停 '+name,exact:true}).click();
 const response=await request.post('/api/v1/opportunities/weekly',{data:{}});expect(response.status()).toBe(401);
});

test('real explicit closed week skips and calendar replacement blocks old enabled revisions',async({page,request})=>{
 const {run}=await seed(request);await calendar(request,true);const name='合成周关闭-'+stamp();await page.goto('/opportunities?run_id='+run.run_id);await save(page,name,true);await enable(page,name);
 await expect.poll(async()=>{const o=await (await request.get('/api/v1/opportunities/weekly')).json();const c=o.configurations.find((c:{name:string})=>c.name===name);return o.recent_runs.find((r:{schedule_id:string})=>r.schedule_id===c?.schedule_id)?.status;}).toBe('SKIPPED_CLOSED');
 await page.getByRole('button',{name:'刷新周筛选与日历'}).click();const task=await latestTask(request,name);await expect(page.locator('article.evidence-card').filter({hasText:task.task_run_id}).getByText('完整日历明确本周没有交易会话，已跳过')).toBeVisible();await calendar(request);await page.getByRole('button',{name:'刷新周筛选与日历'}).click();await expect(page.locator('article.evidence-card').filter({has:page.getByRole('heading',{name:new RegExp('^'+name+' ·')})}).getByText('日历已变化或缺失；请重新保存版本，默认暂停')).toBeVisible();await page.getByRole('button',{name:'暂停 '+name,exact:true}).click();
});
