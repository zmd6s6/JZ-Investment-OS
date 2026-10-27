import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ValuationPage } from "./ValuationPage";
const books=[{portfolio_id:"aaa",name:"合成估值A",base_currency:"CNY",cash_balance:"100"},{portfolio_id:"bbb",name:"合成估值B",base_currency:"CNY",cash_balance:"55"}];
const context={input_hash:"a".repeat(64),output_hash:"b".repeat(64),formula_version:"cny-reference-valuation-v1",source:"MANUAL_MARKET",source_name:"合成来源",input_snapshot:{portfolio_id:"aaa",name:"合成估值A",base_currency:"CNY",cash:"100",captured_at:"2026-10-27T00:00:00Z",holdings:[],policy:{name:null,version_id:null,version:null,status:"MISSING",reason_code:"POLICY_MISSING"}},valuation_status:"REFERENCE_ONLY",nav:"100",market_value:"0",cash_weight:"1",gross_exposure:"0",sector_weights:{},holdings:[],quotes:[],blockers:["POLICY_MISSING","HISTORICAL_VOLATILITY_UNAVAILABLE"],sizing_ready:false,trading_grade:false,auto_trade:false};
const response=(data:unknown,status=200)=>new Response(JSON.stringify(data),{status});
afterEach(()=>{cleanup();vi.restoreAllMocks();});
async function start(){render(<ValuationPage/>);await waitFor(()=>expect(screen.getByLabelText("估值组合")).toHaveValue("aaa"));fireEvent.change(screen.getByLabelText("报价来源名称（与人工行情一致）"),{target:{value:"合成来源"}});}
it("shows exact reference NAV and visible sizing blockers without any write",async()=>{
 const fetch=vi.spyOn(globalThis,"fetch").mockImplementation(async(input)=>response(String(input)==="/api/v1/portfolios"?books:context));
 await start();fireEvent.click(screen.getByRole("button",{name:"读取估值与缺口"}));
 expect(await screen.findByText("参考估值已计算；仍不具备完整仓位计算条件。")).toBeVisible();
 expect(screen.getByText("尚无生效政策版本，不使用测试限额补齐")).toBeVisible();
 expect(screen.getByText("缺少可追溯的历史波动率")).toBeVisible();
 expect(fetch.mock.calls.every(([,init])=>!init?.method||init.method==="GET")).toBe(true);
});
it.each(["portfolio","source"])("late valuation cannot populate changed %s context",async(change)=>{
 let release!:(r:Response)=>void;
 vi.spyOn(globalThis,"fetch").mockImplementation(async(input)=>String(input)==="/api/v1/portfolios"?response(books):new Promise(resolve=>{release=resolve;}));
 await start();fireEvent.click(screen.getByRole("button",{name:"读取估值与缺口"}));await waitFor(()=>expect(release).toBeDefined());
 fireEvent.change(screen.getByLabelText(change==="portfolio"?"估值组合":"报价来源名称（与人工行情一致）"),{target:{value:change==="portfolio"?"bbb":"另一来源"}});
 await act(async()=>release(response(context)));
 await waitFor(()=>expect(screen.getByRole("button",{name:"读取估值与缺口"})).toBeEnabled());
 expect(screen.queryByText("2 · 参考估值结果")).toBeNull();
});
it("failed request gives a retryable Chinese explanation and keeps source input",async()=>{
 vi.spyOn(globalThis,"fetch").mockImplementation(async(input)=>String(input)==="/api/v1/portfolios"?response(books):response({},422));
 await start();fireEvent.click(screen.getByRole("button",{name:"读取估值与缺口"}));
 expect(await screen.findByText("读取失败，请核对组合与来源后重试；原输入已保留。")).toBeVisible();
 expect(screen.getByLabelText("报价来源名称（与人工行情一致）")).toHaveValue("合成来源");
});
it("rejects a mismatched or unexpectedly trading-ready response",async()=>{
 vi.spyOn(globalThis,"fetch").mockImplementation(async(input)=>response(String(input)==="/api/v1/portfolios"?books:{...context,sizing_ready:true}));
 await start();fireEvent.click(screen.getByRole("button",{name:"读取估值与缺口"}));
 expect(await screen.findByText("估值响应与本次组合不一致，未展示旧结果；请重新读取。")).toBeVisible();
 expect(screen.queryByText("2 · 参考估值结果")).toBeNull();
});
