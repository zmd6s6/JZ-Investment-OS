import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { TeamThesisDraft } from "./TeamThesisDraft";

const suggestion={id:"opinion-a:0",opinion_id:"opinion-a",role:"FUNDAMENTAL",stage:"ROUND_1",claim:"合成团队观察",evidence_ids:["evidence-a"]};
const review={analysis_run_id:"run-a",instrument_id:"asset-a",as_of:"2026-10-22",input_hash:"a".repeat(64),base_version_id:"version-a",suggestions:[suggestion],unknowns:["仍需核实的合成问题"],risk_gate:"VETO",limitations:[]};
const response=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status});
const evidence=[{evidence_id:"evidence-a",freshness_status:"FRESH"}];
const props={runId:"run-a",instrumentId:"asset-a",baseVersionId:"version-a",evidence,disabled:false,adopted:false,onApply:vi.fn()};
const impact={pillar_key:"demand",impact:"WEAKEN",reason:"合成需求受挑战",evidence_ids:["evidence-a"],opinion_id:"opinion-a",role:"FUNDAMENTAL",stage:"ROUND_2",baseline_status:"MATCHED",baseline_claim:"原合成需求主张",baseline_pillar_status:"VALID"};
afterEach(()=>{cleanup();vi.restoreAllMocks();props.onApply.mockReset();});

it("displays frozen pillar impacts and conflicting opinions without adoption or writes",async()=>{
  const fetch=vi.spyOn(globalThis,"fetch").mockResolvedValue(response({...review,impacts:[impact,{...impact,impact:"STRENGTHEN",role:"INDUSTRY",reason:"合成行业乐观判断"}]}));
  render(<TeamThesisDraft {...props}/>);
  fireEvent.click(await screen.findByText("团队对逻辑支柱的影响判断（2）"));
  expect(screen.getByText("合成需求受挑战")).toBeVisible();
  expect(screen.getByText("合成行业乐观判断")).toBeVisible();
  expect(screen.getAllByText(/当次基准支柱：原合成需求主张/)).toHaveLength(2);
  expect(props.onApply).not.toHaveBeenCalled();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][1]?.method).toBeUndefined();
});

it("keeps unmatched and unavailable historical impacts explicit",async()=>{
  vi.spyOn(globalThis,"fetch").mockResolvedValue(response({...review,impacts:[{...impact,baseline_status:"UNMATCHED",baseline_claim:null,baseline_pillar_status:null}],limitations:["ADDITIONAL_IMPACTS_NOT_SHOWN:1"]}));
  render(<TeamThesisDraft {...props} evidence={[]}/>);
  await screen.findByText(/未匹配当次基准支柱/);
  expect(screen.getByText(/最多展示100条影响判断/)).toBeInTheDocument();
  expect(screen.getByText(/支持资料当前不可用/)).toBeInTheDocument();
  expect(props.onApply).not.toHaveBeenCalled();
});

it("rejects malformed impact values instead of interpreting free text",async()=>{
  vi.spyOn(globalThis,"fetch").mockResolvedValue(response({...review,impacts:[{...impact,impact:"BUY"}]}));
  render(<TeamThesisDraft {...props}/>);
  expect(await screen.findByText(/团队支柱影响记录格式异常/)).toBeVisible();
  expect(props.onApply).not.toHaveBeenCalled();
});

it("renders untrusted impact reason as text rather than executable HTML",async()=>{
  vi.spyOn(globalThis,"fetch").mockResolvedValue(response({...review,impacts:[{...impact,reason:"<img src=x onerror=alert(1)>合成不可信内容"}]}));
  const view=render(<TeamThesisDraft {...props}/>);
  await screen.findByText("<img src=x onerror=alert(1)>合成不可信内容");
  expect(view.container.querySelector("img")).toBeNull();
  expect(props.onApply).not.toHaveBeenCalled();
});

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

it("only explicit eligible impact selection creates a risk draft callback, never a write",async()=>{
  const eligible={...impact,id:"opinion-a:impact:0"};
  const fetch=vi.spyOn(globalThis,"fetch").mockResolvedValue(response({...review,impacts:[eligible,{...eligible,id:"opinion-a:impact:1",impact:"STRENGTHEN"},{...eligible,id:"opinion-a:impact:2",baseline_status:"UNMATCHED"},{...impact}]}));
  const apply=vi.fn();
  render(<TeamThesisDraft {...props} onApplyRisks={apply}/>);
  const checkbox=await screen.findByRole("checkbox",{name:"带入风险判断 1 · 基本面"});
  expect(checkbox).not.toBeChecked();
  expect(screen.getByRole("button",{name:"将勾选影响加入风险草稿"})).toBeDisabled();
  for(const index of [2,3,4])expect(screen.getByRole("checkbox",{name:`带入风险判断 ${index} · 基本面`})).toBeDisabled();
  fireEvent.click(checkbox);
  fireEvent.click(screen.getByRole("button",{name:"将勾选影响加入风险草稿"}));
  expect(apply).toHaveBeenCalledWith({analysis_run_id:"run-a",suggestion_ids:[],impact_ids:[eligible.id]},[eligible]);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(props.onApply).not.toHaveBeenCalled();
});

it("expired evidence and overly long risk text stay readable but cannot enter risk drafts",async()=>{
  vi.spyOn(globalThis,"fetch").mockResolvedValue(response({...review,impacts:[{...impact,id:"op:impact:0"},{...impact,id:"op:impact:1",reason:"合".repeat(3001)}]}));
  const apply=vi.fn();
  const view=render(<TeamThesisDraft {...props} onApplyRisks={apply}/>);
  expect(await screen.findByRole("checkbox",{name:"带入风险判断 2 · 基本面"})).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox",{name:"带入风险判断 1 · 基本面"}));
  view.rerender(<TeamThesisDraft {...props} evidence={[]} onApplyRisks={apply}/>);
  expect(screen.getByRole("button",{name:"将勾选影响加入风险草稿"})).toBeDisabled();
  expect(apply).not.toHaveBeenCalled();
});

it("duplicate impact identifiers fail closed instead of adopting ambiguous entries",async()=>{
  vi.spyOn(globalThis,"fetch").mockResolvedValue(response({...review,impacts:[{...impact,id:"duplicate"},{...impact,id:"duplicate"}]}));
  render(<TeamThesisDraft {...props} onApplyRisks={vi.fn()}/>);
  expect(await screen.findByText(/团队影响选择标识异常/)).toBeVisible();
  expect(screen.queryByRole("button",{name:"将勾选影响加入风险草稿"})).toBeNull();
});
