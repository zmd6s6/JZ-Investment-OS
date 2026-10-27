import { expect, test } from '@playwright/test';
const token=process.env.INVESTMENT_OS_API_WRITE_TOKEN ?? 'synthetic-mvp201-only';
const headers={Authorization:`Bearer ${token}`};

async function register(request:import('@playwright/test').APIRequestContext,currency='CNY'){
  const response=await request.post('/api/v1/instruments',{headers,data:{market:currency==='CNY'?'SSE':'NASDAQ',symbol:'SYN201'+Date.now()+Math.floor(Math.random()*1000),name:'合成人工行情验收',asset_type:'EQUITY',currency,sector:'Synthetic'}});
  expect(response.status()).toBe(201);return response.json();
}
async function select(page:import('@playwright/test').Page,instrument:{symbol:string}){
  await page.getByLabel('标的搜索').fill(instrument.symbol);
  await page.getByRole('button',{name:new RegExp(instrument.symbol)}).click();
  await page.getByLabel('来源名称').fill('合成公开资料');
}
async function fields(page:import('@playwright/test').Page,expired=false){
  await page.getByLabel('参考价格（人民币）').fill('15.250000000000000001');
  await page.getByLabel('来源出处').fill('synthetic://manual-market');
  const local=(delta:number)=>{const date=new Date(Date.now()+delta);return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,19);};
  for(const label of ['观察时点','生效时点','可获取时点'])await page.getByLabel(label).fill(local(-3600000));
  await page.getByLabel('到期时点').fill(local(expired?-1800000:86400000));
}

test.beforeEach(async({page})=>{await page.addInitScript(t=>sessionStorage.setItem('investment_os_write_token',t),token);});

test('settings to persisted manual quote, trace, refresh and explicit missing/FX states',async({page,request})=>{
  const instrument=await register(request);
  await page.goto('/acceptance');
  await page.getByRole('link',{name:'进入人工行情与币种边界'}).click();
  await expect(page.getByRole('heading',{name:'人工行情与汇率边界'})).toBeVisible();
  await page.goto('/settings');
  await page.getByRole('link',{name:'记录人工行情／查看单币种与FX边界'}).click();
  await expect(page.getByRole('heading',{name:'人工行情与汇率边界'})).toBeVisible();
  await select(page,instrument);await fields(page);
  await page.getByRole('button',{name:'明确保存人工报价'}).click();
  await expect(page.getByText(/人工报价已记录/)).toBeVisible();
  await page.getByRole('button',{name:'读取指定来源报价'}).click();
  await expect(page.getByText('参考价格：15.250000000000000001 CNY')).toBeVisible();
  await expect(page.getByText(/内容摘要：/)).toBeVisible();
  await page.reload();await page.getByRole('button',{name:'读取指定来源报价'}).click();
  await expect(page.getByText('参考价格：15.250000000000000001 CNY')).toBeVisible();
  await page.getByLabel('来源名称').fill('明确不存在的来源');
  await page.getByRole('button',{name:'读取指定来源报价'}).click();
  await expect(page.getByRole('heading',{name:'该来源在此时点没有报价'})).toBeVisible();
  await expect(page.getByText(/参考价格：/)).toHaveCount(0);
  await page.getByLabel('估值基准币种').selectOption('USD');
  await page.getByRole('button',{name:'读取指定来源报价'}).click();
  await expect(page.getByRole('heading',{name:'缺少汇率，跨币种读取已阻止'})).toBeVisible();
  await expect(page.getByText(/没有可用参考价格/)).toBeVisible();
});

test('expired save stays traceable but has no price; invalid input stays editable',async({page,request})=>{
  const instrument=await register(request);await page.goto('/market-data');
  await select(page,instrument);await fields(page,true);
  await page.getByLabel('参考价格（人民币）').fill('NaN');
  await page.getByRole('button',{name:'明确保存人工报价'}).click();
  await expect(page.getByText(/输入未通过校验/)).toBeVisible();
  await expect(page.getByLabel('参考价格（人民币）')).toHaveValue('NaN');
  await page.getByLabel('参考价格（人民币）').fill('15.25');
  await page.getByRole('button',{name:'明确保存人工报价'}).click();
  await expect(page.getByText(/人工报价已记录/)).toBeVisible();
  await page.getByRole('button',{name:'读取指定来源报价'}).click();
  await expect(page.getByRole('heading',{name:'报价已到期，参考价不可用'})).toBeVisible();
  await expect(page.getByText(/内容摘要：/)).toBeVisible();
  await expect(page.getByText(/参考价格：/)).toHaveCount(0);
});

test('non CNY target and mobile guidance remain explicit',async({page,request})=>{
  const instrument=await register(request,'USD');
  await page.setViewportSize({width:390,height:844});await page.goto('/market-data');
  await select(page,instrument);
  await expect(page.getByText('该标的不是人民币报价，缺少FX，不能在首版保存或据此估值。')).toBeVisible();
  await expect(page.getByRole('button',{name:'明确保存人工报价'})).toBeDisabled();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.screenshot({path:'../.runtime/mvp201-mobile.png',fullPage:true});
});
