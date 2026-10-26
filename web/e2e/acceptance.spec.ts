import { expect, test } from "@playwright/test";

test("real delivery manifest survives refresh, links to working UI and never accepts checkpoints",async({page,request},testInfo)=>{
  const response=await request.get("/api/v1/product-acceptance");
  expect(response.ok()).toBe(true);
  const manifest=await response.json();
  expect(manifest.capabilities.every((item:{human_acceptance:string})=>item.human_acceptance==="PENDING")).toBe(true);
  const writes:string[]=[];
  page.on("request",req=>{if(!["GET","HEAD"].includes(req.method()))writes.push(req.url());});
  await page.goto("/acceptance");
  await expect(page.getByRole("heading",{name:"产品进度与验收",level:1,exact:true})).toBeVisible();
  const portfolio=page.getByRole("article",{name:"组合与持仓导入能力状态"});
  await expect(portfolio.getByText("待所有者验收")).toBeVisible();
  await portfolio.getByText("操作指引与失败提示").click();
  await expect(portfolio.getByText(/无效行必须提示错误/)).toBeVisible();
  const analysis=page.getByRole("article",{name:"团队分析与追溯能力状态"});
  await expect(analysis.getByText("尚未实现",{exact:true})).toBeVisible();
  await expect(analysis.getByRole("link")).toHaveCount(0);
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBe(true);
  await page.screenshot({path:testInfo.outputPath("acceptance-390.png"),fullPage:true});
  await portfolio.getByRole("link",{name:"进入组合与持仓导入"}).click();
  await expect(page.getByRole("heading",{name:"我的持仓"})).toBeVisible();
  await page.getByRole("link",{name:"产品进度与验收",exact:true}).click();
  await page.reload();
  await expect(page.getByRole("article",{name:"组合与持仓导入能力状态"}).getByText("待所有者验收")).toBeVisible();
  expect(writes).toEqual([]);
});

test("read failure is visible and explicit retry recovers without a write",async({page})=>{
  let fail=true;
  await page.route("**/api/v1/product-acceptance",async route=>{if(fail)await route.fulfill({status:503,body:"{}"});else await route.continue();});
  await page.goto("/acceptance");
  await expect(page.getByText(/无法读取产品进度/)).toBeVisible();
  await expect(page.getByRole("link",{name:"进入组合与持仓导入"})).toHaveCount(0);
  fail=false;
  await page.getByRole("button",{name:"刷新产品进度"}).click();
  await expect(page.getByRole("link",{name:"进入组合与持仓导入"})).toBeVisible();
});
