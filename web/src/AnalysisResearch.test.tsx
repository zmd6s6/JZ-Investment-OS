import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AnalysisResearch } from "./AnalysisResearch";
afterEach(()=>{cleanup();vi.restoreAllMocks();});
const response=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status});
const view={run_id:"a",status:"RECORDED",committee_session_id:"session-a",input_hash:"hash-a",agents:[],risk:{id:"risk-a",gate:"UNKNOWN",as_of:"2026-10-21",expires_at:"2026-10-22",content_hash:"hash-r",veto:false,veto_codes:[],hard_flags:[],soft_flags:[],evidence_ids:[]},decision_status:"NOT_REGISTERED"};
it("仅明确只读加载并区分未知风险与正式决策缺失",async()=>{
  const fetch=vi.spyOn(globalThis,"fetch").mockResolvedValue(response(view));
  render(<AnalysisResearch runId="a"/>);
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button",{name:"查看研究主表记录"}));
  await screen.findByText(/已保存的风险评估 · 未知/);
  expect(screen.getByText(/正式 Decision 尚未创建/)).toBeVisible();
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("旧报告不补造记录，失败保留已读内容且可只读重试",async()=>{
  const fetch=vi.spyOn(globalThis,"fetch").mockResolvedValueOnce(response({...view,status:"NOT_RECORDED",risk:null})).mockResolvedValueOnce(response({},503));
  render(<AnalysisResearch runId="a"/>);
  fireEvent.click(screen.getByRole("button",{name:"查看研究主表记录"}));
  await screen.findByText(/此运行尚无本版研究主表关联记录/);
  fireEvent.click(screen.getByRole("button",{name:"重新读取研究记录"}));
  await screen.findByRole("alert");
  expect(screen.getByText(/此运行尚无本版研究主表关联记录/)).toBeVisible();
  expect(fetch).toHaveBeenCalledTimes(2);
});
it("切换运行丢弃迟到响应且新运行仍能读取",async()=>{
  let release:(response:Response)=>void=()=>{};
  const fetch=vi.spyOn(globalThis,"fetch").mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;})).mockResolvedValueOnce(response({...view,run_id:"b"}));
  const {rerender}=render(<AnalysisResearch runId="a"/>);
  fireEvent.click(screen.getByRole("button",{name:"查看研究主表记录"}));
  rerender(<AnalysisResearch runId="b"/>);
  fireEvent.click(screen.getByRole("button",{name:"查看研究主表记录"}));
  await screen.findByText(/已保存委员会与风险主表/);
  release(response(view));
  await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(2));
  expect(screen.getByRole("button",{name:"重新读取研究记录"})).toBeEnabled();
});
