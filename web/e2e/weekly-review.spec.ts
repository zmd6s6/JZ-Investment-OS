import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

const fixture = JSON.parse(readFileSync(new URL("../../.runtime/mvp408-browser-fixture.json", import.meta.url), "utf8"));
const headers = { Authorization: "Bearer synthetic-weekly-only" };
test.describe.configure({ mode: "serial" });
test.beforeEach(async ({ context }) => { await context.addInitScript(() => sessionStorage.setItem("investment_os_write_token", "synthetic-weekly-only")); });

function period() {
  const today = new Date();
  const localDate = new Date(today.toLocaleDateString("en-CA", {timeZone:"Asia/Shanghai"})+"T00:00:00Z");
  const start = new Date(localDate); start.setUTCDate(localDate.getUTCDate() - ((localDate.getUTCDay()+6)%7) - 7);
  const end = new Date(start); end.setUTCDate(start.getUTCDate()+6);
  return {start: start.toISOString().slice(0,10), end:end.toISOString().slice(0,10), manifest:Array.from({length:7},(_,i)=>{const d=new Date(start);d.setUTCDate(start.getUTCDate()+i);return `${d.toISOString().slice(0,10)},${[0,6].includes(i)?"OPEN":"CLOSED"}`;}).join("\n")};
}

test("real weekly API PG production Worker and Chrome freeze an independently authorized local report", async ({ page, request }) => {
  test.setTimeout(90000);
  const dates = period();
  const watch = await request.post("/api/v1/watchlist", {headers, data: {market:"SSE", symbol:"629205", name:"205合成测算标的", asset_type:"EQUITY", currency:"CNY", sector:"合成行业"}});
  expect(watch.ok(), await watch.text()).toBeTruthy();
  const overview = await (await request.get("/api/v1/calendar")).json();
  const previous = overview.configurations.find((value: { venue: string }) => value.venue === "SSE");
  const imported = await request.post("/api/v1/calendar/imports", { headers, data: { request_id: crypto.randomUUID(), expected_version: previous?.version ?? 0, venue: "SSE", source_name: "Synthetic explicitly complete weekly calendar", source_version: `weekly-${Date.now()}`, confirmed_source: true, csv_text: `business_date,close_at\n${dates.start},15:00\n${dates.end},15:00\n` } });
  expect(imported.ok(), await imported.text()).toBeTruthy();
  const calendar = await imported.json();
  const before = await (await request.get(`/api/v1/analysis/runs?portfolio_id=${fixture.ids.portfolio}`)).json();
  const beforeDecisions = await (await request.get("/api/v1/decisions")).json();
  expect((await (await request.get("/api/v1/settings/model-providers")).json()).length).toBe(0);
  await page.goto("/calendar");
  const panel = page.getByRole("region", { name: "周度组合复核" });
  await expect(panel.getByRole("heading", { name: "周度组合复核", exact: true })).toBeVisible();
  await panel.getByLabel("周度组合", { exact: true }).selectOption(fixture.ids.portfolio);
  await panel.getByLabel("周度显式日历").selectOption(calendar.import_id);
  await panel.getByLabel("205合成测算标的 629205", {exact:true}).check();
  const name = `408完整周复核-${Date.now()}`;
  await panel.getByLabel("周度任务名称").fill(name);
  await panel.getByLabel("首周起日（必须周一）").fill(dates.start);
  await panel.getByLabel("末周末日（必须周日）").fill(dates.end);
  const local = async (value: number) => page.evaluate(timestamp => { const date = new Date(timestamp), pad = (n: number) => String(n).padStart(2, "0"); return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`; }, value);
  await panel.getByLabel("周度授权开始（浏览器本地时区）").fill(await local(Date.now() - 600000));
  await panel.getByLabel("周度授权截止", { exact: true }).fill(await local(Date.now() + 3600000));
  await panel.getByLabel("周报使用期限（天）").fill("7");
  await panel.getByLabel("周度本地报价来源").fill("synthetic-205-reference");
  await panel.getByLabel("周度允许本地资料来源（每行一个）").fill("205明确合成数值来源");
  await panel.getByLabel("逐日完整覆盖清单").fill(dates.manifest);
  await panel.getByLabel(/我独立确认完整周覆盖/).check();
  await panel.getByRole("button", { name: "预览完整周度授权（不保存）" }).click();
  await expect(panel.getByRole("heading", { name: "完整周度授权预览" })).toBeVisible();
  await expect(panel.getByRole("button", { name: "保存周度授权为暂停" })).toBeDisabled();
  await panel.getByLabel(/已核对本次全部周度范围/).check();
  const savedResponse = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/runtime/weekly");
  await panel.getByRole("button", { name: "保存周度授权为暂停" }).click();
  const saved = await savedResponse;
  expect(saved.ok(), await saved.text()).toBeTruthy();
  const config = await saved.json();
  expect(config.enabled).toBe(false);
  expect(config.prepared.command.frequency).toBe("WEEKLY_AFTER_COMPLETE_CALENDAR_WEEK");
  expect(config.prepared.command.model_profile_ids).toEqual([]);
  expect(config.prepared.command.data_profile_ids).toEqual([]);
  const card = panel.locator("article").filter({ has: page.getByRole("heading", { name: new RegExp(name) }) });
  await expect(card).toContainText("已暂停");
  expect((await (await request.get(`/api/v1/runtime/weekly/reports?schedule_id=${config.schedule_id}`)).json()).length).toBe(0);
  await card.getByLabel(/我已核对此保存周度授权/).check();
  await card.getByRole("button", { name: "启用周度复核" }).click();
  await expect(card).toContainText("已启用");
  await expect.poll(async () => (await (await request.get(`/api/v1/runtime/weekly/reports?schedule_id=${config.schedule_id}`)).json()).length, { timeout: 30000 }).toBe(1);
  await panel.getByRole("button", { name: "刷新周度状态与报告" }).click();
  await panel.getByRole("button", { name: "打开周报冻结快照" }).first().click();
  const report = panel.getByRole("region", { name: "周报冻结快照" });
  await expect(report.getByRole("heading", { name: /周度组合复核报告/ })).toBeVisible();
  await expect(report).toContainText("若今天未持有是否重新进入: 未提供判断");
  await expect(report).toContainText("CURRENT_BOOK_READ_NOT_HISTORICAL_CLOSE_SNAPSHOT");
  await expect(report).toContainText("SIMULATION / NO AUTO TRADE");
  await expect(panel.getByRole("status")).toContainText("只读重放冻结快照");
  const reports = await (await request.get(`/api/v1/runtime/weekly/reports?schedule_id=${config.schedule_id}`)).json();
  const current = reports.find((value: { schedule_id: string }) => value.schedule_id === config.schedule_id);
  expect(current.phase).toBe("DEGRADED");
  expect(current.period_start).toBe(dates.start);
  expect(current.period_end).toBe(dates.end);
  expect(current.local_inputs.portfolio.portfolio_id).toBe(fixture.ids.portfolio);
  expect(current.holdings.length).toBeGreaterThan(0);
  expect(current.local_inputs.members.some((value: {in_watchlist: boolean}) => value.in_watchlist)).toBe(true);
  expect(current.valuation.nav).not.toBeNull();
  const replay = await (await request.get(`/api/v1/runtime/weekly/reports/${current.report_id}/replay`)).json();
  expect(replay.content_hash).toBe(current.content_hash);
  await page.screenshot({ path: "../.runtime/mvp408-real-weekly-report.png", fullPage: true });
  await page.reload();
  await expect(panel.getByRole("heading", { name: new RegExp(name) })).toContainText("已启用");
  await card.getByLabel(/我已核对此保存周度授权/).check();
  await card.getByRole("button", { name: "永久撤销周度授权" }).click();
  await expect(card).toContainText("已永久撤销");
  await expect(card.getByRole("button", { name: "启用周度复核" })).toBeDisabled();
  expect((await (await request.get(`/api/v1/analysis/runs?portfolio_id=${fixture.ids.portfolio}`)).json()).length).toBe(before.length);
  expect((await (await request.get("/api/v1/decisions")).json()).length).toBe(beforeDecisions.length);
  expect((await (await request.get("/api/v1/settings/model-providers")).json()).length).toBe(0);
  await page.screenshot({ path: "../.runtime/mvp408-real-weekly-chain.png", fullPage: true });
});

test("partial natural week is visibly rejected with input retained and no weekly authorization", async ({ page, request }) => {
  const before = await (await request.get("/api/v1/runtime/weekly")).json();
  const dates = period(), calendar = (await (await request.get("/api/v1/calendar")).json()).configurations.find((value: { venue: string }) => value.venue === "SSE");
  await page.goto("/calendar");
  const panel = page.getByRole("region", { name: "周度组合复核" });
  await panel.getByLabel("周度组合", { exact: true }).selectOption(fixture.ids.portfolio);
  await panel.getByLabel("周度显式日历").selectOption(calendar.import_id);
  await panel.getByLabel("205合成测算标的 629205", {exact:true}).check();
  await panel.getByLabel("周度任务名称").fill("408拒绝部分周");
  await panel.getByLabel("首周起日（必须周一）").fill(new Date(new Date(dates.start+"T00:00:00Z").getTime()+86400000).toISOString().slice(0,10));
  await panel.getByLabel("末周末日（必须周日）").fill(dates.end);
  await panel.getByLabel("周度授权开始（浏览器本地时区）").fill("2026-11-01T08:00");
  await panel.getByLabel("周度授权截止", { exact: true }).fill("2026-12-01T08:00");
  await panel.getByLabel("周报使用期限（天）").fill("7");
  await panel.getByLabel("周度本地报价来源").fill("synthetic-205-reference");
  await panel.getByLabel("逐日完整覆盖清单").fill(dates.manifest);
  await panel.getByLabel(/我独立确认完整周覆盖/).check();
  await panel.getByRole("button", { name: "预览完整周度授权（不保存）" }).click();
  await expect(panel.getByRole("alert")).toContainText("必须选择完整周一至周日");
  await expect(panel.getByLabel("周度任务名称")).toHaveValue("408拒绝部分周");
  await expect(panel.getByRole("button", { name: "保存周度授权为暂停" })).toHaveCount(0);
  expect((await (await request.get("/api/v1/runtime/weekly")).json()).length).toBe(before.length);
  await page.screenshot({ path: "../.runtime/mvp408-rejected-week.png", fullPage: true });
});


test("more than fifty real authorizations remain visible after revocation", async ({ page, request }) => {
  test.setTimeout(120000);
  const original = (await (await request.get("/api/v1/runtime/weekly")).json())[0];
  expect(original.revoked).toBe(true);
  for (let index = 0; index < 51; index++) {
    const command = { ...original.prepared.command, request_id: crypto.randomUUID(), schedule_id: crypto.randomUUID(), expected_version: 0, name: `分页合成${index}` };
    const preview = await request.post("/api/v1/runtime/weekly/preview", { headers, data: command });
    expect(preview.ok(), await preview.text()).toBeTruthy();
    const prepared = await preview.json();
    const saved = await request.post("/api/v1/runtime/weekly", { headers, data: { command, preview_hash: prepared.content_hash } });
    expect(saved.ok(), await saved.text()).toBeTruthy();
    expect((await saved.json()).enabled).toBe(false);
  }
  await page.goto("/calendar");
  const panel = page.getByRole("region", { name: "周度组合复核" });
  const oldName = String(original.prepared.command.name);
  await expect(panel.getByRole("heading", { name: new RegExp(oldName) })).toHaveCount(0);
  await panel.getByRole("button", { name: "加载更多周度授权" }).click();
  await expect(panel.getByRole("heading", { name: new RegExp(oldName) })).toContainText("已永久撤销");
  await expect(panel.getByRole("status")).toContainText("已加载下一页");
  await page.screenshot({ path: "../.runtime/mvp408-pagination-review.png", fullPage: true });
});

test("narrow real report replay and failed reads retain no stale body or write path", async ({ page, request }) => {
  await page.setViewportSize({width:390,height:844});
  const history = await (await request.get("/api/v1/runtime/weekly/history")).json();
  expect(history.length).toBeGreaterThan(0);
  expect((await request.get(`/api/v1/runtime/weekly/reports/${crypto.randomUUID()}/replay`)).status()).toBe(422);
  let mutations = 0;
  page.on("request", req => {if (["POST","PUT","DELETE","PATCH"].includes(req.method())) mutations++;});
  await page.goto("/calendar");
  const panel = page.getByRole("region", {name:"周度组合复核"});
  await panel.getByRole("button", {name:"打开周报冻结快照"}).first().click();
  await expect(panel.getByRole("region", {name:"周报冻结快照"})).toBeVisible();
  await expect(panel).toContainText(history[0].report_id);
  await page.route("**/api/v1/runtime/weekly/reports/*/replay", route => route.fulfill({status:503,contentType:"application/json",body:JSON.stringify({detail:{code:"SYNTHETIC_REPLAY_UNAVAILABLE",message:"合成报告读取失败"}})}));
  await panel.getByRole("button", {name:"打开周报冻结快照"}).first().click();
  await expect(panel.getByRole("alert")).toContainText("只读报告加载失败，已清空旧正文");
  await expect(panel.getByRole("region", {name:"周报冻结快照"})).toHaveCount(0);
  await page.route("**/api/v1/runtime/weekly/history", route => route.fulfill({status:503,contentType:"application/json",body:JSON.stringify({detail:"合成历史读取失败"})}));
  await panel.getByRole("button", {name:"刷新周度状态与报告"}).click();
  await expect(panel.getByRole("alert")).toBeVisible();
  await expect(panel.getByRole("button", {name:"预览完整周度授权（不保存）"})).toBeDisabled();
  expect(mutations).toBe(0);
  await page.screenshot({path:"../.runtime/mvp408-narrow-read-failure.png",fullPage:true});
});

test("closed weeks never claim an uncaptured baseline in the real weekly report UI", async ({page,request}) => {
  test.setTimeout(180000);
  const original=(await (await request.get("/api/v1/runtime/weekly")).json()).find((value:{prepared:unknown})=>value.prepared).prepared.command;
  const endWeek=period();
  for(const earlierCapture of [false,true]) {
    const weeks=earlierCapture?3:2;
    const first=new Date(new Date(endWeek.start+"T00:00:00Z").getTime()-(weeks-1)*7*86400000);
    const start=first.toISOString().slice(0,10);
    const day=(offset:number)=>new Date(first.getTime()+offset*86400000).toISOString().slice(0,10);
    const opens=new Set([endWeek.start,endWeek.end,...(earlierCapture?[day(0),day(6)]:[])]);
    const pointer=(await (await request.get("/api/v1/calendar")).json()).configurations.find((value:{venue:string})=>value.venue==="SSE");
    const imported=await request.post("/api/v1/calendar/imports",{headers,data:{request_id:crypto.randomUUID(),expected_version:pointer.version,venue:"SSE",source_name:"Synthetic explicit closed gap",source_version:`closed-gap-${Date.now()}`,confirmed_source:true,csv_text:"business_date,close_at\n"+[...opens].sort().map(value=>`${value},15:00\n`).join("")}});
    expect(imported.ok(),await imported.text()).toBeTruthy();
    const calendar=await imported.json();
    const command={...original,request_id:crypto.randomUUID(),schedule_id:crypto.randomUUID(),expected_version:0,name:`408闭市基线-${earlierCapture}-${Date.now()}`,calendar_import_id:calendar.import_id,coverage_start:start,coverage_end:endWeek.end,calendar_days:Object.fromEntries(Array.from({length:weeks*7},(_,i)=>[day(i),opens.has(day(i))?"OPEN":"CLOSED"])),valid_from:new Date(Date.now()-60000).toISOString(),valid_until:new Date(Date.now()+3600000).toISOString()};
    const preview=await request.post("/api/v1/runtime/weekly/preview",{headers,data:command});
    expect(preview.ok(),await preview.text()).toBeTruthy();
    const saved=await request.post("/api/v1/runtime/weekly",{headers,data:{command,preview_hash:(await preview.json()).content_hash}});
    expect(saved.ok(),await saved.text()).toBeTruthy();
    const enabled=await request.post(`/api/v1/runtime/weekly/${command.schedule_id}/mode`,{headers,data:{request_id:crypto.randomUUID(),expected_version:(await saved.json()).version,action:"ENABLE",confirmed:true}});
    expect(enabled.ok(),await enabled.text()).toBeTruthy();
    await expect.poll(async()=> (await (await request.get(`/api/v1/runtime/weekly/reports?schedule_id=${command.schedule_id}`)).json()).length,{timeout:45000}).toBe(weeks);
    const reports=await (await request.get(`/api/v1/runtime/weekly/reports?schedule_id=${command.schedule_id}`)).json();
    const latest=reports.find((value:{period_start:string})=>value.period_start===endWeek.start);
    const closed=reports.find((value:{phase:string})=>value.phase==="CLOSED_WEEK_SKIPPED");
    expect(closed.local_inputs).toBeNull();
    if(earlierCapture) {
      const firstOpen=reports.find((value:{period_start:string})=>value.period_start===start);
      expect(latest.baseline_report_id).toBe(firstOpen.report_id);
      expect(latest.baseline_report_id).not.toBe(closed.report_id);
      expect(latest.baseline_status).toBe("COMPARABLE_BASELINE");
    } else {
      expect(latest.baseline_report_id).toBeNull();
      expect(latest.baseline_status).toBe("FIRST_RUN_NO_BASELINE");
      expect(latest.holdings.every((value:{core_change:unknown,tactical_change:unknown})=>value.core_change===null&&value.tactical_change===null)).toBe(true);
    }
    await page.goto("/calendar");
    const panel=page.getByRole("region",{name:"周度组合复核"});
    await panel.locator("article").filter({hasText:latest.report_id}).getByRole("button",{name:"打开周报冻结快照"}).click();
    const report=panel.getByRole("region",{name:"周报冻结快照"});
    await expect(report).toContainText(earlierCapture?"同授权既往捕获快照":"首次运行, 无可比基线");
    if(!earlierCapture) {
      await expect(report).toContainText("Core变化未提供");
      await expect(report).not.toContainText("同授权既往捕获快照");
    }
    await report.screenshot({path:`../.runtime/mvp408-closed-gap-${earlierCapture?"actual":"first"}-baseline.png`});
    const revoked=await request.post(`/api/v1/runtime/weekly/${command.schedule_id}/mode`,{headers,data:{request_id:crypto.randomUUID(),expected_version:(await enabled.json()).version,action:"REVOKE",confirmed:true}});
    expect(revoked.ok(),await revoked.text()).toBeTruthy();
  }
});
