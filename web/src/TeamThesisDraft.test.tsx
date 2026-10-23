import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { TeamThesisDraft } from "./TeamThesisDraft";

const suggestion={id:"opinion-a:0",opinion_id:"opinion-a",role:"FUNDAMENTAL",stage:"ROUND_1",claim:"合成团队观察",evidence_ids:["evidence-a"]};
const review={analysis_run_id:"run-a",instrument_id:"asset-a",as_of:"2026-10-22",input_hash:"a".repeat(64),base_version_id:"version-a",suggestions:[suggestion],unknowns:["仍需核实的合成问题"],risk_gate:"VETO",limitations:[]};
const response=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status});
const evidence=[{evidence_id:"evidence-a",freshness_status:"FRESH"}];
const props={runId:"run-a",instrumentId:"asset-a",baseVersionId:"version-a",evidence,disabled:false,adopted:false,onApply:vi.fn()};
afterEach(()=>{cleanup();vi.restoreAllMocks();props.onApply.mockReset();});

it("requires an explicit selection, retains unknowns and historical veto, and only reads saved data",async()=>{
  const fetch=vi.spyOn(globalThis,"fetch").mockResolvedValue(response(review));
  render(<TeamThesisDraft {...props}/>);
  const checkbox=await screen.findByRole("checkbox");
  expect(checkbox).not.toBeChecked();
  expect(screen.getByText("仍需核实的合成问题")).toBeVisible();
  expect(screen.getByText(/当时风险门：否决/)).toBeVisible();
  const apply=screen.getByRole("button",{name:"将勾选观点加入编辑草稿"});
  expect(apply).toBeDisabled();
  fireEvent.click(checkbox);fireEvent.click(apply);
  expect(props.onApply).toHaveBeenCalledWith({analysis_run_id:"run-a",suggestion_ids:["opinion-a:0"]},[suggestion]);
  expect(fetch.mock.calls).toHaveLength(1);
  expect(fetch.mock.calls[0][1]?.method).toBeUndefined();
});

it("blocks stale baseline and unavailable evidence without switching source",async()=>{
  vi.spyOn(globalThis,"fetch").mockImplementation(async()=>response(review));
  const view=render(<TeamThesisDraft {...props} baseVersionId="version-b"/>);
  expect(await screen.findByText(/当前投资逻辑已不同于本次分析基准/)).toBeVisible();
  expect(screen.getByRole("checkbox")).toBeDisabled();
  view.rerender(<TeamThesisDraft {...props} evidence={[{evidence_id:"evidence-a",freshness_status:"EXPIRED"}]}/>);
  expect(screen.getByRole("checkbox")).toBeDisabled();
  expect(screen.getByText(/支持资料已不新鲜/)).toBeVisible();
  expect(props.onApply).not.toHaveBeenCalled();
});

it("failure and malformed source permit explicit read-only retry",async()=>{
  const fetch=vi.spyOn(globalThis,"fetch").mockRejectedValueOnce(new TypeError("合成读取失败")).mockResolvedValueOnce(response({...review,instrument_id:"wrong"})).mockResolvedValueOnce(response(review));
  render(<TeamThesisDraft {...props}/>);
  await screen.findByText(/无法连接本地服务/);
  fireEvent.click(screen.getByRole("button",{name:"重试读取团队观点"}));
  await screen.findByText(/团队草稿来源响应不完整或标的不匹配/);
  fireEvent.click(screen.getByRole("button",{name:"重试读取团队观点"}));
  expect(await screen.findByRole("checkbox")).not.toBeChecked();
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(props.onApply).not.toHaveBeenCalled();
});

it("late response from another run cannot replace the current draft source",async()=>{
  let release!:(response:Response)=>void;
  vi.spyOn(globalThis,"fetch").mockImplementation(async url=>String(url).includes("run-a")?new Promise<Response>(resolve=>{release=resolve;}):response({...review,analysis_run_id:"run-b",suggestions:[{...suggestion,claim:"新运行的合成观察"}]}));
  const view=render(<TeamThesisDraft {...props}/>);
  await waitFor(()=>expect(release).toBeDefined());
  view.rerender(<TeamThesisDraft {...props} runId="run-b"/>);
  await screen.findByText("新运行的合成观察");
  release(response(review));
  await waitFor(()=>expect(screen.queryByText("合成团队观察")).toBeNull());
});
