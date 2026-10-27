import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { CalendarPage, parseCalendarOverview } from "./CalendarPage";

const empty={schema_version:"1.0",scope:"CALENDAR_STATUS_ONLY_NO_PAID_CALLS",auto_trade:false,configurations:[],recent_runs:[]};
const config={venue:"SSE",market_timezone:"Asia/Shanghai",version:1,import_id:"import-a",enabled:false,source_name:"合成来源",source_version:"test-v1",content_hash:"a".repeat(64),imported_at:"2026-10-23T08:00:00Z",session_count:1,first_business_date:"2026-10-23",last_business_date:"2026-10-23",next_close_at:null};
const preview={schema_version:"1.0",venue:"SSE",market_timezone:"Asia/Shanghai",source_name:"合成来源",source_version:"test-v1",content_hash:"a".repeat(64),sessions:[{business_date:"2026-10-23",close_at_utc:"2026-10-23T07:00:00Z"}]};
const response=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status});
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.useRealTimers();});

async function fill(){
  await screen.findByText("尚无已保存日历，不会调度任何产品状态任务。");
  fireEvent.change(screen.getByLabelText("日历来源名称"),{target:{value:"合成来源"}});
  fireEvent.change(screen.getByLabelText("来源版本"),{target:{value:"test-v1"}});
  fireEvent.change(screen.getByLabelText("日历CSV内容"),{target:{value:"business_date,close_at\n2026-10-23,15:00"}});
  fireEvent.click(screen.getByRole("checkbox",{name:"我已核对来源与时段，确认有权导入这些日历数据。"}));
}

it("preview is explicit, does not save, and editing the source invalidates consent and preview",async()=>{
  const fetch=vi.spyOn(globalThis,"fetch").mockImplementation(async(input,init)=>String(input).endsWith("/preview")?response(preview):response(empty));
  render(<CalendarPage/>);await fill();
  expect(fetch.mock.calls).toHaveLength(1);
  fireEvent.click(screen.getByRole("button",{name:"预览日历（不保存）"}));
  await screen.findByText("待确认预览 · 1条时段");
  expect(fetch.mock.calls.filter(([url])=>String(url).endsWith("/imports"))).toHaveLength(0);
  fireEvent.change(screen.getByLabelText("来源版本"),{target:{value:"new-version"}});
  expect(screen.queryByText("待确认预览 · 1条时段")).toBeNull();
  expect(screen.getByRole("checkbox",{name:"我已核对来源与时段，确认有权导入这些日历数据。"})).not.toBeChecked();
});

it("unknown save outcome retains the draft and reuses exactly the same request identifier",async()=>{
  const writes:Record<string,unknown>[]=[];
  let saved=false;
  vi.spyOn(globalThis,"fetch").mockImplementation(async(input,init)=>{
    const url=String(input);
    if(url.endsWith("/preview"))return response(preview);
    if(url.endsWith("/imports")){writes.push(JSON.parse(String(init?.body)));if(writes.length===1)throw new TypeError("synthetic failure");saved=true;return response(config);}
    return response(saved?{...empty,configurations:[config]}:empty);
  });
  render(<CalendarPage/>);await fill();
  fireEvent.click(screen.getByRole("button",{name:"预览日历（不保存）"}));
  await screen.findByText("待确认预览 · 1条时段");
  fireEvent.click(screen.getByRole("checkbox",{name:"我确认按此预览导入；新版本默认暂停，相同内容保持原启用状态。"}));
  fireEvent.click(screen.getByRole("button",{name:"确认导入日历"}));
  await screen.findByText(/日历保存结果尚未确认/);
  expect(screen.getByLabelText("日历CSV内容")).toHaveValue("business_date,close_at\n2026-10-23,15:00");
  fireEvent.click(screen.getByRole("button",{name:"确认导入日历"}));
  await screen.findByText(/已保存并核对日历。当前已暂停/);
  expect(writes).toHaveLength(2);expect(writes[0]).toEqual(writes[1]);
  expect(screen.getByRole("button",{name:"启用无付费状态报告"})).toBeDisabled();
});

it("enabling requires its own explicit acknowledgement and does not call model endpoints",async()=>{
  const fetch=vi.spyOn(globalThis,"fetch").mockImplementation(async(input,init)=>String(input).endsWith("/mode")?response({...config,enabled:true,version:2}):response({...empty,configurations:[config]}));
  render(<CalendarPage/>);
  const button=await screen.findByRole("button",{name:"启用无付费状态报告"});
  expect(button).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox",{name:"我仅启用该市场已导入时段的状态报告；不调用付费模型、研究来源或交易。"}));
  fireEvent.click(button);
  await screen.findByText(/仅日历状态报告已启用/);
  const mode=fetch.mock.calls.find(([url])=>String(url).endsWith("/mode"));
  expect(JSON.parse(String(mode?.[1]?.body))).toMatchObject({expected_version:1,enabled:true,status_only_acknowledgement:true});
  expect(fetch.mock.calls.every(([url])=>String(url).startsWith("/api/v1/calendar"))).toBe(true);
});

it("HTTP failure and malformed JSON are actionable without echoing server fragments",async()=>{
  vi.spyOn(globalThis,"fetch").mockResolvedValueOnce(new Response("synthetic-private-fragment",{status:200})).mockResolvedValueOnce(response(empty));
  render(<CalendarPage/>);
  expect(await screen.findByText("日历响应格式异常，请刷新重试。")).toBeVisible();
  expect(screen.queryByText(/synthetic-private-fragment/)).toBeNull();
  fireEvent.click(screen.getByRole("button",{name:"刷新日历与运行记录"}));
  await screen.findByText("尚无已保存日历，不会调度任何产品状态任务。");
});

it.each([{...empty,auto_trade:true},{...empty,configurations:[config,config]},{...empty,configurations:[{...config,market_timezone:"UTC"}]},{...empty,recent_runs:[{task_run_id:"bad",task_name:"calendar_status_SSE",as_of:"2026-10-23T07:00:00Z",status:"SUCCEEDED",attempt:1,started_at:"2026-10-23T07:00:00Z",finished_at:"2026-10-23T07:00:00Z",error_code:null,report:null}]}])("invalid states fail closed instead of fabricating health or a completed report",value=>{
  expect(()=>parseCalendarOverview(value)).toThrow();
});

it("stalled reads release controls at a bounded deadline and ignore late success",async()=>{
  vi.useFakeTimers();let release!:(value:Response)=>void;
  vi.spyOn(globalThis,"fetch").mockImplementation(()=>new Promise(resolve=>{release=resolve;}));
  render(<CalendarPage/>);
  await act(async()=>{await vi.advanceTimersByTimeAsync(15000);});
  expect(screen.getByText(/读取日历与运行记录超时/)).toBeVisible();
  expect(screen.getByRole("button",{name:"刷新日历与运行记录"})).toBeEnabled();
  release(response({...empty,configurations:[config]}));vi.useRealTimers();
  await waitFor(()=>expect(screen.queryByText("合成来源 · 版本 test-v1 · 配置版本 1")).toBeNull());
});
