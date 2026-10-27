import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PortfolioPage } from "./PortfolioPage";
const response=(body:unknown,status=200)=>new Response(JSON.stringify(body),{status});
const portfolio={portfolio_id:"cash-a",name:"合成现金组合",base_currency:"CNY",cash_balance:"10000.25",status:"ACTIVE",as_of:"2026-10-27T00:00:00Z",missing_pricing:true,positions:[]};
afterEach(()=>{cleanup();vi.restoreAllMocks();sessionStorage.clear();});
it.each([false,true])("a late holdings refresh preserves the cash draft and submits its exact value (cash failure=%s)",async(failed)=>{
 let reads=0;let release!:(r:Response)=>void;let cashBody="";
 vi.spyOn(globalThis,"fetch").mockImplementation(async(input,init)=>{
  const url=String(input);
  if(url.endsWith("/positions"))return response({});
  if(url.endsWith("/cash")){cashBody=String(init?.body);return failed?response({detail:"PORTFOLIO_WRITE_INVALID"},422):response({});}
  if(url.includes("import-audits"))return response([]);
  if(url==="/api/v1/portfolios"){
   if(++reads===2)return new Promise(resolve=>{release=resolve;});
   return response([{...portfolio,cash_balance:reads>2?"9000.50":portfolio.cash_balance}]);
  }
  return response({});
 });
 render(<PortfolioPage/>);
 await waitFor(()=>expect(screen.getByLabelText("更新现金（当前组合）")).toHaveValue("10000.25"));
 fireEvent.change(screen.getByLabelText("代码"),{target:{value:"629881"}});
 fireEvent.change(screen.getByLabelText("名称"),{target:{value:"合成标的"}});
 fireEvent.click(screen.getByRole("button",{name:"保存持仓"}));
 await screen.findByText("持仓已保存");
 fireEvent.change(screen.getByLabelText("更新现金（当前组合）"),{target:{value:"9000.50"}});
 await act(async()=>release(response([portfolio])));
 await waitFor(()=>expect(screen.getByRole("button",{name:"更新现金"})).toBeEnabled());
 expect(screen.getByLabelText("更新现金（当前组合）")).toHaveValue("9000.50");
 fireEvent.click(screen.getByRole("button",{name:"更新现金"}));
 await screen.findByText(failed?"现金输入无效，请填写非负数值；输入已保留。":"现金已更新");
 expect(JSON.parse(cashBody)).toEqual({cash_balance:"9000.50"});
 expect(screen.getByLabelText("更新现金（当前组合）")).toHaveValue("9000.50");
});
it.each([{context:"new draft",failed:false},{context:"other portfolio",failed:false},{context:"new draft",failed:true},{context:"other portfolio",failed:true}])("late cash response preserves $context and isolates feedback (failed=$failed)",async({context,failed})=>{
 let release!:(r:Response)=>void;let readCount=0;
 const other={...portfolio,portfolio_id:"cash-b",name:"合成现金组合B",cash_balance:"55"};
 vi.spyOn(globalThis,"fetch").mockImplementation(async(input)=>{
  const url=String(input);
  if(url.endsWith("/cash"))return new Promise(resolve=>{release=resolve;});
  if(url.includes("import-audits"))return response([]);
  if(url==="/api/v1/portfolios")return response([{...portfolio,cash_balance:++readCount>1?"9000.50":portfolio.cash_balance},other]);
  return response({});
 });
 render(<PortfolioPage/>);
 await waitFor(()=>expect(screen.getByLabelText("更新现金（当前组合）")).toHaveValue("10000.25"));
 fireEvent.change(screen.getByLabelText("更新现金（当前组合）"),{target:{value:"9000.50"}});
 fireEvent.click(screen.getByRole("button",{name:"更新现金"}));
 await waitFor(()=>expect(release).toBeDefined());
 if(context==="new draft")fireEvent.change(screen.getByLabelText("更新现金（当前组合）"),{target:{value:"8000.25"}});
 else fireEvent.click(screen.getByRole("button",{name:/合成现金组合B/}));
 await act(async()=>release(failed?response({detail:"synthetic-old-cash-error"},422):response({})));
 await waitFor(()=>expect(screen.getByRole("button",{name:"更新现金"})).toBeEnabled());
 expect(screen.getByLabelText("更新现金（当前组合）")).toHaveValue(context==="new draft"?"8000.25":"55");
 expect(screen.queryByText("现金已更新")).toBeNull();
 expect(screen.queryByText("synthetic-old-cash-error")).toBeNull();
});
