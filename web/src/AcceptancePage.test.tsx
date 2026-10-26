import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";
import { AcceptancePage, parseAcceptance } from "./AcceptancePage";

const item={key:"portfolio",label:"组合与持仓导入",work_item:"MVP-101",engineering:"IMPLEMENTED",integration:"INTEGRATED",human_acceptance:"PENDING",service:"ASSEMBLED",route:"/portfolio",detail:"当前构建已有接通证据，不代表所有者接受。",steps:["创建组合后刷新核对。"],failure:"错误必须明确显示。"};
const snapshot={schema_version:"1.0",release:"MVP-BETA",auto_trade:false,evidence_basis:"BUILD_MANIFEST_AND_SERVICE_ASSEMBLY",capabilities:[item]};
const response=(data:unknown,status=200)=>new Response(JSON.stringify(data),{status});
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.useRealTimers();window.history.replaceState({},"","/");});

it("routes the real product page and keeps engineering, integration and human acceptance separate",async()=>{
  window.history.replaceState({},"","/acceptance");
  const fetch=vi.spyOn(globalThis,"fetch").mockResolvedValue(response(snapshot));
  render(<App/>);
  expect(await screen.findByText("待所有者验收")).toBeVisible();
  expect(screen.getByRole("link",{name:"进入组合与持仓导入"})).toHaveAttribute("href","/portfolio");
  expect(screen.queryByRole("button",{name:/接受|通过验收/})).toBeNull();
  fireEvent.click(screen.getByText("操作指引与失败提示"));
  expect(screen.getByText("失败时应看到：错误必须明确显示。")).toBeVisible();
  expect(fetch).toHaveBeenCalledWith("/api/v1/product-acceptance",expect.objectContaining({signal:expect.any(AbortSignal)}));
});

it("unavailable and unimplemented paths expose no misleading entry",async()=>{
  vi.spyOn(globalThis,"fetch").mockResolvedValue(response({...snapshot,capabilities:[{...item,service:"UNAVAILABLE",route:null},{...item,key:"analysis",label:"团队分析",engineering:"NOT_IMPLEMENTED",integration:"NOT_IMPLEMENTED",service:"NOT_APPLICABLE",route:null,steps:[]}]}));
  render(<AcceptancePage/>);
  expect(await screen.findByText("当前部署未装配，入口暂不可用")).toBeVisible();
  expect(screen.queryByRole("link",{name:/^进入/})).toBeNull();
});

it("malformed JSON shows a Chinese error without echoing response fragments",async()=>{
  vi.spyOn(globalThis,"fetch").mockResolvedValue(new Response("synthetic-private-fragment",{status:200}));
  render(<AcceptancePage/>);
  expect(await screen.findByText("产品进度响应格式异常，请重试或检查服务版本。")).toBeVisible();
  expect(screen.queryByText(/synthetic-private-fragment/)).toBeNull();
});

it("failure clears success and explicit retry performs another GET only",async()=>{
  const fetch=vi.spyOn(globalThis,"fetch").mockResolvedValueOnce(response(snapshot)).mockResolvedValueOnce(response({},503)).mockResolvedValueOnce(response(snapshot));
  render(<AcceptancePage/>);
  await screen.findByText("待所有者验收");
  fireEvent.click(screen.getByRole("button",{name:"刷新产品进度"}));
  await screen.findByText(/无法读取产品进度/);
  expect(screen.queryByText("待所有者验收")).toBeNull();
  fireEvent.click(screen.getByRole("button",{name:"刷新产品进度"}));
  await screen.findByText("待所有者验收");
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(fetch.mock.calls.every(([,init])=>!init?.method)).toBe(true);
});

it.each([
  {...snapshot,auto_trade:true},
  {...snapshot,capabilities:[]},
  {...snapshot,capabilities:[item,item]},
  {...snapshot,capabilities:[{...item,route:"https://external.example.test"}]},
  {...snapshot,capabilities:[{...item,human_acceptance:"ACCEPTED"}]},
  {...snapshot,capabilities:[{...item,service:"UNAVAILABLE"}]},
])("rejects malformed or unsupported claims rather than fabricating success",value=>{
  expect(()=>parseAcceptance(value)).toThrow();
});

it("stalled reads release the UI after the deadline and ignore late success",async()=>{
  vi.useFakeTimers();
  let release!:(value:Response)=>void;
  vi.spyOn(globalThis,"fetch").mockImplementation(()=>new Promise(resolve=>{release=resolve;}));
  render(<AcceptancePage/>);
  await act(async()=>{await vi.advanceTimersByTimeAsync(15000);});
  expect(screen.getByText(/读取产品进度超时/)).toBeVisible();
  expect(screen.getByRole("button",{name:"刷新产品进度"})).toBeEnabled();
  release(response(snapshot));
  vi.useRealTimers();
  await waitFor(()=>expect(screen.queryByText("待所有者验收")).toBeNull());
});
