import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PortfolioPage } from "./PortfolioPage";

const portfolio=(id:string,name:string)=>({portfolio_id:id,name,base_currency:"CNY",cash_balance:"0",status:"ACTIVE",as_of:"2026-10-26T00:00:00Z",missing_pricing:true,positions:[]});
const preview={total_rows:1,can_commit:true,requires_conflict_policy:false,content_hash:"a".repeat(64),positions_hash:"b".repeat(64),valid:[{line_number:2,status:"VALID",symbol:"629891",reason:null}],invalid:[],duplicates:[],conflicts:[]};
const response=(data:unknown,status=200)=>new Response(JSON.stringify(data),{status});
const selectedName=()=>document.querySelector(".stat-card strong")?.textContent;
afterEach(()=>{cleanup();vi.restoreAllMocks();sessionStorage.clear();});

function install(previewFetch:()=>Promise<Response>){
  return vi.spyOn(globalThis,"fetch").mockImplementation(async(input,init)=>{
    const url=String(input);
    if(url.includes("/csv/preview"))return previewFetch();
    if(url.includes("import-audits"))return response([]);
    if(url==="/api/v1/portfolios")return response([portfolio("aaa","合成组合A"),portfolio("bbb","合成组合B")]);
    if(init?.method)return response({},500);
    return response({});
  });
}

it.each([false,true])("a late preview response for A cannot return to B (failed=%s)",async(failed)=>{
  let release!:(r:Response)=>void;
  install(()=>new Promise(resolve=>{release=resolve;}));
  render(<PortfolioPage/>);
  await waitFor(()=>expect(selectedName()).toBe("合成组合A"));
  fireEvent.change(screen.getByLabelText("CSV 内容"),{target:{value:"合成CSV A"}});
  fireEvent.click(screen.getByRole("button",{name:"预览"}));
  await waitFor(()=>expect(release).toBeDefined());
  fireEvent.click(screen.getByRole("button",{name:/合成组合B/}));
  await act(async()=>release(failed?response({detail:"synthetic-late-error"},422):response(preview)));
  await waitFor(()=>expect(screen.getByRole("button",{name:"预览"})).toBeEnabled());
  expect(selectedName()).toBe("合成组合B");
  expect(screen.getByRole("button",{name:"确认导入"})).toBeDisabled();
  expect(screen.queryByText("synthetic-late-error")).toBeNull();
  expect(screen.queryByText(/预览完成/)).toBeNull();
});

it("editing CSV invalidates the in-flight preview instead of reopening confirmation",async()=>{
  let release!:(r:Response)=>void;
  install(()=>new Promise(resolve=>{release=resolve;}));
  render(<PortfolioPage/>);
  await waitFor(()=>expect(selectedName()).toBe("合成组合A"));
  fireEvent.change(screen.getByLabelText("CSV 内容"),{target:{value:"旧合成CSV"}});
  fireEvent.click(screen.getByRole("button",{name:"预览"}));
  await waitFor(()=>expect(release).toBeDefined());
  fireEvent.change(screen.getByLabelText("CSV 内容"),{target:{value:"新合成CSV"}});
  await act(async()=>release(response(preview)));
  await waitFor(()=>expect(screen.getByRole("button",{name:"预览"})).toBeEnabled());
  expect(screen.getByRole("button",{name:"确认导入"})).toBeDisabled();
  expect(screen.getByLabelText("CSV 内容")).toHaveValue("新合成CSV");
});

it("new CSV content requires an explicit new conflict choice",async()=>{
  const conflict={...preview,requires_conflict_policy:true,valid:[],conflicts:[{line_number:2,status:"CONFLICT",symbol:"629891",reason:"合成冲突",existing_core_quantity:"1"}]};
  install(async()=>response(conflict));
  render(<PortfolioPage/>);
  await waitFor(()=>expect(selectedName()).toBe("合成组合A"));
  fireEvent.change(screen.getByLabelText("CSV 内容"),{target:{value:"旧CSV"}});
  fireEvent.click(screen.getByRole("button",{name:"预览"}));
  fireEvent.click(await screen.findByRole("radio",{name:/替换/}));
  expect(screen.getByRole("button",{name:"确认导入"})).toBeEnabled();
  fireEvent.change(screen.getByLabelText("CSV 内容"),{target:{value:"新CSV"}});
  fireEvent.click(screen.getByRole("button",{name:"预览"}));
  expect(await screen.findByRole("radio",{name:/替换/})).not.toBeChecked();
  expect(screen.getByRole("button",{name:"确认导入"})).toBeDisabled();
});

it.each([{failed:false,context:"portfolio"},{failed:true,context:"portfolio"},{failed:false,context:"csv"}])("late confirmation for A keeps changed $context context (failed=$failed)",async({failed,context})=>{
  let release!:(r:Response)=>void;
  const confirms:string[]=[];
  const fetch=vi.spyOn(globalThis,"fetch").mockImplementation(async(input,init)=>{
    const url=String(input);
    if(url.includes("/csv/preview"))return response(preview);
    if(url.includes("/csv/confirm")){confirms.push(url);return new Promise(resolve=>{release=resolve;});}
    if(url.includes("import-audits"))return response([]);
    if(url==="/api/v1/portfolios")return response([portfolio("aaa","合成组合A"),portfolio("bbb","合成组合B")]);
    return response({});
  });
  render(<PortfolioPage/>);
  await waitFor(()=>expect(selectedName()).toBe("合成组合A"));
  fireEvent.change(screen.getByLabelText("CSV 内容"),{target:{value:"合成待确认CSV"}});
  fireEvent.click(screen.getByRole("button",{name:"预览"}));
  await waitFor(()=>expect(screen.getByRole("button",{name:"确认导入"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button",{name:"确认导入"}));
  await waitFor(()=>expect(release).toBeDefined());
  if(context==="portfolio")fireEvent.click(screen.getByRole("button",{name:/合成组合B/}));
  else fireEvent.change(screen.getByLabelText("CSV 内容"),{target:{value:"确认期间新填写的CSV"}});
  await act(async()=>release(failed?response({detail:"synthetic-A-write-failed"},409):response({imported_count:1,skipped_count:0,audit_id:"audit-a",applied:[]})));
  await waitFor(()=>expect(screen.getByRole("button",{name:"预览"})).toBeEnabled());
  expect(confirms).toEqual(["/api/v1/portfolios/aaa/csv/confirm"]);
  expect(selectedName()).toBe(context==="portfolio"?"合成组合B":"合成组合A");
  if(context==="csv")expect(screen.getByLabelText("CSV 内容")).toHaveValue("确认期间新填写的CSV");
  expect(screen.queryByRole("heading",{name:"导入对账记录"})).toBeNull();
  expect(screen.queryByText(/已导入 1 笔/)).toBeNull();
  expect(screen.queryByText("synthetic-A-write-failed")).toBeNull();
  expect(fetch.mock.calls.some(([url])=>String(url).includes("/bbb/csv/confirm"))).toBe(false);
});
