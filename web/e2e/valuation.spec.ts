import {expect,test,type APIRequestContext,type Page} from '@playwright/test';
test.skip(process.env.E2E_MVP202_SYNTHETIC!=='1','仅独立MVP202合成栈');
const token=process.env.INVESTMENT_OS_API_WRITE_TOKEN??'synthetic-mvp202-only';const headers={Authorization:`Bearer ${token}`};
async function fixture(request:APIRequestContext,currency='CNY'){
 const name=`合成估值-${currency}-${Date.now()}`;const r=await request.post('/api/v1/portfolios',{headers,data:{name,base_currency:currency,cash_balance:'100'}});expect(r.status()).toBe(201);const book=await r.json();
 const p=await request.post(`/api/v1/portfolios/${book.portfolio_id}/positions`,{headers,data:{market:'SSE',symbol:`SYN202${Date.now()}`,name:'合成估值标的',asset_type:'EQUITY',currency,sector:'合成行业',core_quantity:'10',tactical_quantity:'2',average_cost:'12',core_average_cost:'11',tactical_average_cost:'13'}});expect(p.status()).toBe(200);return p.json();
}
async function calculate(page:Page,id:string){await page.goto(`/valuation?portfolio_id=${id}`);await expect(page.getByLabel('估值组合')).toHaveValue(id);await page.getByLabel('报价来源名称（与人工行情一致）').fill('合成估值来源');await page.getByRole('button',{name:'读取估值与缺口',exact:true}).click();}
test.beforeEach(async({context})=>{await context.addInitScript(t=>sessionStorage.setItem('investment_os_write_token',t),token);});
test('real UI quote to exact bucket valuation and reload retains explicit sizing gaps',async({page,request})=>{
 const book=await fixture(request);await calculate(page,book.portfolio_id);await expect(page.getByText('价格未齐全，完整估值已停止。',{exact:true})).toBeVisible();
 const instrument=book.positions[0];await page.goto(`/market-data?instrument_id=${instrument.instrument_id}&source_name=${encodeURIComponent('合成估值来源')}`);await expect(page.getByText(new RegExp(`当前标的：SSE ${instrument.symbol}`))).toBeVisible();
 await page.getByLabel('参考价格（人民币）').fill('19.25');await page.getByLabel('来源出处').fill('synthetic://valuation-202');const local=(delta:number)=>{const d=new Date(Date.now()+delta);return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,19);};for(const label of ['观察时点','生效时点','可获取时点'])await page.getByLabel(label).fill(local(-3600000));await page.getByLabel('到期时点').fill(local(3600000));await page.getByRole('button',{name:'明确保存人工报价'}).click();await expect(page.getByText(/人工报价已记录/)).toBeVisible();
 await calculate(page,book.portfolio_id);await expect(page.getByText('参考估值已计算；仍不具备完整仓位计算条件。',{exact:true})).toBeVisible();await expect(page.getByText('331',{exact:true})).toBeVisible();await expect(page.getByText('192.5 / 38.5',{exact:true})).toBeVisible();await expect(page.getByText('缺少可追溯的历史波动率',{exact:true})).toBeVisible();await expect(page.getByText(/Evidence /)).toBeVisible();
 const data=await(await request.get(`/api/v1/valuation/portfolios/${book.portfolio_id}?source=MANUAL_MARKET&source_name=${encodeURIComponent('合成估值来源')}`)).json();expect(Number(data.nav)).toBe(331);expect(data.sizing_ready).toBe(false);expect(data.trading_grade).toBe(false);expect(data.input_snapshot.policy.reason_code).toBe('POLICY_MISSING');
 await page.reload();await expect(page.getByText('2 · 参考估值结果',{exact:true})).toHaveCount(0);await page.getByLabel('估值组合').selectOption(book.portfolio_id);await page.getByLabel('报价来源名称（与人工行情一致）').fill('合成估值来源');await page.getByRole('button',{name:'读取估值与缺口',exact:true}).click();await expect(page.getByText('331',{exact:true})).toBeVisible();await page.screenshot({path:'../.runtime/mvp202-reference-valuation.png',fullPage:true});
});
test('missing FX and read failure stay explicit and editable',async({page,request})=>{
 const book=await fixture(request,'USD');await calculate(page,book.portfolio_id);await expect(page.getByText('缺少汇率，未计算组合估值。',{exact:true})).toBeVisible();await expect(page.getByText('存在非人民币资产或记账币种，缺少汇率，整组停止估值',{exact:true})).toBeVisible();
 await page.route('**/api/v1/valuation/portfolios/**',r=>r.fulfill({status:503,contentType:'application/json',body:'{}'}));await page.getByRole('button',{name:'读取估值与缺口',exact:true}).click();await expect(page.getByText('当前服务未装配估值能力，请同步版本后重试。',{exact:true})).toBeVisible();await expect(page.getByLabel('报价来源名称（与人工行情一致）')).toHaveValue('合成估值来源');
});
test('mobile valuation keeps CNY and missing-data guidance usable without horizontal page overflow',async({page,request})=>{
 const book=await fixture(request);await page.setViewportSize({width:390,height:844});await calculate(page,book.portfolio_id);await expect(page.getByText('价格未齐全，完整估值已停止。',{exact:true})).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);await page.screenshot({path:'../.runtime/mvp202-valuation-mobile.png',fullPage:true});
});
