import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PortfolioPage } from "./PortfolioPage";

afterEach(()=>{cleanup();vi.restoreAllMocks();sessionStorage.clear();});
const response=(body:unknown,status=200)=>new Response(JSON.stringify(body),{status});

it.each([
  {field:"长期仓数量",value:"-1",button:"保存持仓",message:"持仓输入无效，请检查市场、代码、名称、数量与均价；数量和均价不能为负数。输入已保留。"},
  {field:"更新现金（当前组合）",value:"-1",button:"更新现金",message:"现金输入无效，请填写非负数值；输入已保留。"},
  {field:"组合名称",value:"",button:"创建组合",message:"组合输入无效，请检查名称、记账币种与现金；现金不能为负数。输入已保留。"},
])("$button explains invalid input and preserves the user's value",async({field,value,button,message})=>{
  vi.spyOn(globalThis,"fetch").mockImplementation(async(input,init)=>{
    if(init?.method)return response({detail:"PORTFOLIO_WRITE_INVALID"},422);
    if(String(input).includes("import-audits"))return response([]);
    return response([{portfolio_id:"aaa",name:"合成组合",base_currency:"CNY",cash_balance:"0",status:"ACTIVE",as_of:"2026-10-26T00:00:00Z",missing_pricing:true,positions:[]}]);
  });
  render(<PortfolioPage/>);
  await waitFor(()=>expect(screen.getByRole("button",{name:"保存持仓"})).toBeEnabled());
  if(button==="保存持仓"){
    fireEvent.change(screen.getByLabelText("代码"),{target:{value:"629892"}});
    fireEvent.change(screen.getByLabelText("名称"),{target:{value:"合成标的"}});
  }
  fireEvent.change(screen.getByLabelText(field),{target:{value}});
  fireEvent.click(screen.getByRole("button",{name:button}));
  expect(await screen.findByText(message)).toBeVisible();
  expect(screen.getByLabelText(field)).toHaveValue(value);
  expect(screen.queryByText("PORTFOLIO_WRITE_INVALID")).toBeNull();
});
