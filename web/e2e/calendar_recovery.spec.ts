import { expect, test } from "@playwright/test";
import { execFile, spawn } from "node:child_process";
import path from "node:path";
import { promisify } from "node:util";

test("旧源A暂停竞态失败后，更正B在真实Worker恢复，旧失败与已成功日期不被覆盖",async({page,request})=>{
  test.skip(process.env.E2E_BASE_URL!=="http://127.0.0.1:18110"||!process.env.E2E_CALENDAR_FIXTURE_DATABASE,"仅MVP401独占合成恢复栈，常驻Worker须先停止");
  const token=process.env.INVESTMENT_OS_API_WRITE_TOKEN!;
  await page.addInitScript(value=>sessionStorage.setItem("investment_os_write_token",value),token);
  const python=path.resolve("..", ".venv",process.platform==="win32"?"Scripts/python.exe":"bin/python");
  const fixture=path.resolve("e2e/calendar_recovery_fixture.py");
  await page.goto("/calendar");
  await page.getByLabel("日历市场").selectOption("SZSE");
  await page.getByLabel("日历来源名称").fill("合成失败恢复日历（非真实来源）");
  async function importVersion(version:string,close:string){
    await page.getByLabel("来源版本",{exact:true}).fill(version);
    await page.getByLabel("日历CSV内容").fill(`business_date,close_at\n2026-10-21,${close}`);
    await page.getByLabel("我已核对来源与时段，确认有权导入这些日历数据。").check();
    await page.getByRole("button",{name:"预览日历（不保存）"}).click();
    await expect(page.getByRole("heading",{name:/待确认预览/})).toBeVisible();
    await page.getByLabel("我确认按此预览导入；新版本默认暂停，相同内容保持原启用状态。").check();
    await page.getByRole("button",{name:"确认导入日历"}).click();
    await expect(page.getByRole("article",{name:"深圳证券交易所日历配置"}).getByRole("heading")).toContainText("已暂停");
  }
  async function enable(){
    const config=page.getByRole("article",{name:"深圳证券交易所日历配置"});
    await config.getByLabel("我仅启用该市场已导入时段的状态报告；不调用付费模型、研究来源或交易。").check();
    await config.getByRole("button",{name:"启用无付费状态报告"}).click();
    await expect(config.getByRole("heading")).toContainText("已启用");
  }
  await importVersion("synthetic-recovery-A","15:00");await enable();
  // A controlled fixture pauses through the real application boundary between plan/commit.
  await promisify(execFile)(python,[fixture,"pause-race"],{env:process.env,timeout:15000});
  await page.getByRole("button",{name:"刷新日历与运行记录"}).click();
  await expect(page.getByRole("heading",{name:"calendar_status_SZSE · 状态任务失败",exact:true})).toBeVisible();
  const before=await(await request.get("/api/v1/calendar")).json();
  const failed=before.recent_runs.find((run:{task_name:string})=>run.task_name==="calendar_status_SZSE");
  expect(failed.status).toBe("FAILED");
  await importVersion("synthetic-recovery-B","15:01");await enable();
  const worker=spawn(python,[fixture,"loop"],{env:process.env,stdio:"ignore"});
  try{
    await expect(page.getByRole("heading",{name:"calendar_status_SZSE · 状态报告已完成",exact:true})).toBeVisible({timeout:20000});
    const recovered=await(await request.get("/api/v1/calendar")).json();
    const runs=recovered.recent_runs.filter((run:{task_name:string})=>run.task_name==="calendar_status_SZSE");
    expect(runs).toHaveLength(2);
    expect(runs.find((run:{task_run_id:string})=>run.task_run_id===failed.task_run_id)).toEqual(failed);
    expect(runs.find((run:{status:string})=>run.status==="SUCCEEDED").report).toMatchObject({source_version:"synthetic-recovery-B",paid_calls:0,auto_trade:false});
    await importVersion("synthetic-recovery-C","15:02");await enable();
    // An explicit Worker pass after C guarantees the check, without an arbitrary delay.
    await promisify(execFile)(python,[fixture,"loop-once"],{env:process.env,timeout:15000});
    await page.reload();
    const after=await(await request.get("/api/v1/calendar")).json();
    expect(after.recent_runs.filter((run:{task_name:string})=>run.task_name==="calendar_status_SZSE")).toEqual(runs);
    await expect(page.getByRole("heading",{name:"calendar_status_SZSE · 状态任务失败",exact:true})).toBeVisible();
    await page.getByRole("article",{name:"深圳证券交易所日历配置"}).getByRole("button",{name:"暂停状态报告"}).click();
  }finally{worker.kill();}
});
