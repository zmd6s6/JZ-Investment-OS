import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
const token=process.env.INVESTMENT_OS_API_WRITE_TOKEN??'synthetic-mvp402-only';
const headers={Authorization:`Bearer ${token}`};
const stamp=()=>Date.now()+'-'+Math.floor(Math.random()*10000);
const local=(delta:number)=>{const date=new Date(Date.now()+delta);return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16);};
async function instrument(request:APIRequestContext,currency='CNY'){
 const id=stamp();const response=await request.post('/api/v1/instruments',{headers,data:{market:currency==='CNY'?'SSE':'NASDAQ',symbol:'SYN402'+id,name:'合成402-'+id,asset_type:'EQUITY',currency,sector:'Synthetic'}});expect(response.status()).toBe(201);return response.json();
}
async function quote(request:APIRequestContext,item:{instrument_id:string},source:string,expired=false){
 const response=await request.post('/api/v1/market-data/manual-quotes',{headers,data:{request_id:crypto.randomUUID(),instrument_id:item.instrument_id,source_name:source,source_locator:'synthetic://quote/'+stamp(),currency:'CNY',price:'10',observed_at:new Date(Date.now()-1800000).toISOString(),effective_at:new Date(Date.now()-1800000).toISOString(),available_at:new Date(Date.now()-1800000).toISOString(),expires_at:new Date(Date.now()+(expired?-60000:86400000)).toISOString()}});expect(response.ok()).toBe(true);return response.json();
}
async function add(page:Page,item:{symbol:string}){await page.getByLabel('标的搜索').fill(item.symbol);await page.getByRole('button',{name:new RegExp(item.symbol)}).click();}
async function sources(page:Page,source:string){await page.getByLabel('报价来源名称').fill(source);await page.getByLabel('基础事实来源名称').fill('合成年报-'+source);}
async function facts(page:Page,profit='20'){
 await page.getByRole('button',{name:'读取报价并绑定Evidence'}).click();await expect(page.getByText(/已读取人工报价；/)).toBeVisible();
 await page.getByLabel('事实出处').fill('synthetic://annual-report');await page.getByLabel('有来源行业').fill('Synthetic');await page.getByLabel('完整自然年年度').fill(String(new Date().getUTCFullYear()-1));
 await page.getByLabel('本年度营收',{exact:true}).fill('100');await page.getByLabel('上年度营收',{exact:true}).fill('80');await page.getByLabel('年度归属普通股股东利润').fill(profit);await page.getByLabel('完整自然年年报稀释EPS（元／股）').fill(profit==='20'?'0.2':'0.01');await page.getByLabel('前收盘',{exact:true}).fill('8');await page.getByLabel('是否停牌').selectOption('false');await page.getByLabel('报价与年度稀释EPS口径').selectOption('true');
 for(const label of ['事实观察时点','事实生效时点','事实可获取时点'])await page.getByLabel(label).fill(local(-7200000));await page.getByLabel('事实到期时点').fill(local(86400000));await page.getByLabel('前收盘时点').fill(local(-86400000));
 await page.getByRole('button',{name:'保存基础事实'}).click();await expect(page.getByText(/事实已保存，未经独立核实/)).toBeVisible();await expect(page.getByText(/事实已保存，未经独立核实/)).toBeInViewport();
}
async function query(page:Page,name:string){
 await page.getByLabel('范围名称').fill(name);await page.getByLabel('范围出处').fill('synthetic://finite-scope');await page.getByLabel('最低年度归属利润率').fill('0.1');await page.getByLabel('最低营收同比增幅').fill('0.1');await page.getByLabel('最高年报稀释PE（非TTM）').fill('60');await page.getByLabel('最低相对前收盘变化').fill('0');await page.getByLabel('最多研究候选（1至20）').fill('1');await page.getByRole('button',{name:'运行本次确定性筛选'}).click();await expect(page.getByRole('heading',{name:'本次筛选：'+name})).toBeVisible();
}
test.beforeEach(async({page})=>{await page.addInitScript(t=>sessionStorage.setItem('investment_os_write_token',t),token);});

test('real manual facts UI produces a bounded candidate with reasons, source/time and persistent history',async({page,request},info)=>{
 const a=await instrument(request),b=await instrument(request),source='合成行情-'+stamp();await quote(request,a,source);await quote(request,b,source);
 const external:string[]=[];page.on('request',req=>{if(!req.url().startsWith('http://127.0.0.1:18113/'))external.push(req.url());});
 await page.goto('/acceptance');const card=page.getByRole('article',{name:'有限范围机会漏斗能力状态'});await expect(card.getByText('部分实现',{exact:true})).toBeVisible();await card.getByRole('link',{name:'进入有限范围机会漏斗'}).click();await expect(page.getByRole('heading',{name:'机会漏斗',level:1})).toBeVisible();
 await add(page,a);await sources(page,source);await facts(page);
 await add(page,b);await facts(page,'1');
 const name='合成正常-'+stamp();await query(page,name);
 await expect(page.getByText('待深研的研究候选（人工资料未核实）',{exact:false})).toHaveCount(1);await expect(page.getByText(/年报稀释PE（非TTM）：50/)).toBeVisible();await expect(page.getByText(/利润率低于本次查询下限/)).toBeVisible();
 await page.getByText('来源、Evidence与后续条件').first().click();await expect(page.locator('.evidence-card').first().getByText(/事实出处：synthetic:\/\/annual-report/)).toBeVisible();await expect(page.getByText(/查询规则摘要：/)).toBeVisible();
 const id=new URL(page.url()).searchParams.get('run_id');const before=await request.get('/api/v1/opportunities/runs/'+id);expect(before.ok()).toBe(true);const frozen=await before.json();expect(frozen.deep_research).toBe('NOT_PROVIDED');expect(frozen.candidate_ids).toHaveLength(1);expect(frozen.auto_trade).toBe(false);
 await page.reload();await expect(page.getByRole('heading',{name:'本次筛选：'+name})).toBeVisible();await expect(page.getByText(/年报稀释PE（非TTM）：50/)).toBeVisible();expect((await (await request.get('/api/v1/opportunities/runs/'+id)).json())).toEqual(frozen);expect(external).toEqual([]);
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBe(true);await page.screenshot({path:info.outputPath('opportunities-390.png'),fullPage:true});
});

test('missing facts and expired source stop the same production funnel without old-price fallback',async({page,request})=>{
 const a=await instrument(request),source='合成缺项-'+stamp();await quote(request,a,source);await page.goto('/opportunities');await add(page,a);await sources(page,source);await query(page,'合成缺项-'+stamp());await expect(page.getByText(/需补：指定来源未提供基础事实/)).toBeVisible();await expect(page.getByText(/有界研究候选 0 \/ 1/)).toBeVisible();
 await quote(request,a,source,true);await query(page,'合成过期-'+stamp());await expect(page.getByText(/人工报价已到期/)).toBeVisible();await expect(page.getByText(/有界研究候选 0 \/ 1/)).toBeVisible();
});

test('invalid fact input stays editable and non-CNY is explicit FX failure',async({page,request})=>{
 const a=await instrument(request),source='合成输入-'+stamp();await quote(request,a,source);await page.goto('/opportunities');await add(page,a);await sources(page,source);await facts(page);
 await page.getByLabel('年度归属普通股股东利润').fill('NaN');await page.getByRole('button',{name:'保存基础事实'}).click();await expect(page.getByText(/输入未通过校验/)).toBeVisible();await expect(page.getByLabel('年度归属普通股股东利润')).toHaveValue('NaN');
 const usd=await instrument(request,'USD');await add(page,usd);await expect(page.getByText('该标的不是人民币；缺FX，首版不保存或换算。')).toBeVisible();await expect(page.getByRole('button',{name:'保存基础事实'})).toBeDisabled();await page.getByRole('button',{name:'移除 '+a.symbol}).click();await query(page,'合成FX-'+stamp());await expect(page.getByText(/跨币种缺FX（不默认1:1）/)).toBeVisible();
});
